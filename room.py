import asyncio,json
from board import ServerBoard

MAX_HP=100
ABILITY_COST=10
RED=0
GREEN=1
BLUE=2
YELLOW=3
PURPLE=4

class Room:
    def __init__(self,code,public=False,display_name=None):
        self.code=code;self.public=public;self.display_name=display_name
        self.sockets=[None,None];self.spectators=[]
        self.board=ServerBoard()
        self.hp=[100,100]
        self.max_hp=[100,100]
        self.shield=[0,0]
        self.color_scores=[[0]*7,[0]*7]
        self.player_names=["Player 1","Player 2"]
        self.starting_player=0;self.turn=0;self.winner=None;self.move_number=0
        self.ability_slots=[1,0];self.own_turn_count=[1,0];self.extra_turn_bank=[0,0]
        self.restart_ready=[False,False];self.restart_pending=False

    @property
    def player_count(self):return sum(1 for s in self.sockets if s is not None)
    @property
    def spectator_count(self):return len(self.spectators)
    @property
    def is_full(self):return self.player_count>=2
    @property
    def is_empty(self):return self.player_count==0 and self.spectator_count==0
    @property
    def is_live(self):return self.public and self.player_count==2 and self.winner is None

    def public_info(self):
        return {"code":self.code,"name":self.display_name or self.code,"players":self.player_count,"spectators":self.spectator_count,"open":not self.is_full,"live":self.is_live}

    def add_socket(self,s):
        for i,v in enumerate(self.sockets):
            if v is None:self.sockets[i]=s;return i
        return None

    def remove_socket(self,s):
        for i,v in enumerate(self.sockets):
            if v is s:self.sockets[i]=None;return i
        return None

    def add_spectator(self,s):
        if s not in self.spectators:self.spectators.append(s)

    def remove_spectator(self,s):
        if s in self.spectators:self.spectators.remove(s)

    def state_payload(self,extra=None):
        d={
            "type":"state","room":self.code,"room_name":self.display_name or self.code,"public":self.public,
            "board":self.board.grid,"hp":self.hp,"max_hp":self.max_hp,"shield":self.shield,"color_scores":self.color_scores,
            "player_names":self.player_names,"starting_player":self.starting_player,
            "turn":self.turn,"winner":self.winner,"players":self.player_count,"spectators":self.spectator_count,
            "ability_slots":self.ability_slots,"own_turn_count":self.own_turn_count,"extra_turn_bank":self.extra_turn_bank,
            "restart_ready":self.restart_ready,"restart_pending":self.restart_pending,"move_number":self.move_number,
            "rules_version":50,
        }
        if extra:d.update(extra)
        return d

    async def broadcast(self,extra=None):
        raw=json.dumps(self.state_payload(extra))
        for s in list(self.sockets):
            if s is not None:
                try:await s.send(raw)
                except Exception:self.remove_socket(s)
        for s in list(self.spectators):
            try:await s.send(raw)
            except Exception:self.remove_spectator(s)

    async def set_player_name(self,p,name):
        self.player_names[p]=str(name or "").strip()[:20] or f"Player {p+1}"
        await self.broadcast({"event":"player_name"})

    def _apply_damage(self,target,amount):
        """Server-authoritative damage: shield first, HP second."""
        amount=max(0,int(amount))

        absorbed=min(self.shield[target],amount)
        self.shield[target]-=absorbed
        amount-=absorbed

        if amount>0:
            self.hp[target]=max(0,self.hp[target]-amount)

        return absorbed,amount

    def _apply_scoring_result(self,p,result):
        """
        The ONLY online board-result application path.
        Includes points, white shield gain and gray damage.
        """
        o=1-p

        points=result.get("color_points",[0]*7)
        for i,v in enumerate(points):
            self.color_scores[p][i]+=int(v)

        self.shield[p]=min(100,self.shield[p]+int(result.get("shield_gain",0)))

        self._apply_damage(
            o,
            result.get("damage",0),
        )

        if self.hp[o]<=0:
            self.winner=p

    def yellow_available(self,p):
        return self.own_turn_count[p]>0 and self.own_turn_count[p]%2==0

    def ability_available(self,p,a):
        if p not in (0,1):return False,"invalid_player"
        if self.winner is not None:return False,"game_over"
        if self.player_count<2:return False,"waiting_for_opponent"
        if p!=self.turn:return False,"not_your_turn"
        if a not in (RED,GREEN,BLUE,YELLOW,PURPLE):return False,"invalid_ability"
        if self.color_scores[p][a]<ABILITY_COST:return False,"not_enough_points"
        if a==GREEN:return ((False,"hp_already_full") if self.hp[p]>=self.max_hp[p] else (True,None))
        if self.ability_slots[p]<=0:return False,"ability_limit_reached"
        if a==YELLOW and not self.yellow_available(p):return False,"yellow_not_available_this_turn"
        return True,None

    async def use_ability(self,p,a,target_color=None):
        ok,reason=self.ability_available(p,a)
        if not ok:return {"ok":False,"reason":reason}

        o=1-p

        if a==PURPLE:
            try:target_color=int(target_color)
            except Exception:return {"ok":False,"reason":"purple_target_required"}
            if target_color<0 or target_color>=5:return {"ok":False,"reason":"invalid_purple_target"}

            # Spend only after target validation.
            self.color_scores[p][PURPLE]-=ABILITY_COST
            self.ability_slots[p]-=1

            result=self.board.clear_selected_color(target_color)
            if result is None:
                self.color_scores[p][PURPLE]+=ABILITY_COST
                self.ability_slots[p]+=1
                return {"ok":False,"reason":"invalid_purple_target"}

            # Purple uses the exact same scoring application as a board move.
            self._apply_scoring_result(p,result)

            await self.broadcast({
                "event":"ability","ability_player":p,"ability":PURPLE,
                "target_color":target_color,
                "animation_steps":result["animation_steps"],
                "specials":result["specials"],
                "board_regenerated":result["board_regenerated"],
                "awarded_color_points":result["color_points"],
                "gray_removed":result["gray_removed"],
                "white_removed":result.get("white_removed",0),
                "shield_gain":result.get("shield_gain",0),
            })
            return {"ok":True}

        self.color_scores[p][a]-=ABILITY_COST

        if a==GREEN:
            self.hp[p]=min(self.max_hp[p],self.hp[p]+15)
        else:
            self.ability_slots[p]-=1
            if a==RED:
                self.max_hp[o]=max(0,self.max_hp[o]-15)
                self.hp[o]=min(self.hp[o],self.max_hp[o])
                if self.hp[o]<=0:self.winner=p
            elif a==BLUE:self.max_hp[p]+=5
            elif a==YELLOW:self.extra_turn_bank[p]+=1

        await self.broadcast({"event":"ability","ability_player":p,"ability":a})
        return {"ok":True}

    def _begin_turn(self,p):
        self.turn=p;self.ability_slots=[0,0];self.ability_slots[p]=1;self.own_turn_count[p]+=1

    def _resolve_next_turn(self,p,extra):
        if extra:self.extra_turn_bank[p]+=1
        if self.extra_turn_bank[p]>0:
            self.extra_turn_bank[p]-=1
            return p
        return 1-p

    async def make_move(self,p,a,b):
        if self.winner is not None:return {"ok":False,"reason":"game_over"}
        if self.player_count<2:return {"ok":False,"reason":"waiting_for_opponent"}
        if p!=self.turn:return {"ok":False,"reason":"not_your_turn"}

        result=self.board.resolve_swap(a,b)
        if result is None:
            await self.broadcast({"event":"invalid","invalid_player":p})
            return {"ok":False,"reason":"no_match"}

        # Exactly one authoritative scoring application.
        self._apply_scoring_result(p,result)
        self.move_number+=1

        if self.winner is None:
            self._begin_turn(self._resolve_next_turn(p,result.get("extra_turn",False)))

        payload=dict(result)
        payload.update({
            "event":"move",
            "mover":p,
            "move_a":list(a),
            "move_b":list(b),
            "awarded_color_points":result["color_points"],
        })
        await self.broadcast(payload)
        return {"ok":True}

    async def set_restart_ready(self,p):
        if self.player_count<2:return {"ok":False,"reason":"waiting_for_opponent"}
        if self.winner is None:return {"ok":False,"reason":"game_not_over"}
        if self.restart_pending:return {"ok":True}
        self.restart_ready[p]=True
        n=sum(1 for x in self.restart_ready if x)
        await self.broadcast({"event":"restart_ready","ready_count":n})
        if n==2:
            self.restart_pending=True
            asyncio.create_task(self._start_new_game())
        return {"ok":True}

    async def _start_new_game(self):
        await asyncio.sleep(.65)
        if self.player_count<2 or not all(self.restart_ready):
            self.restart_pending=False;return

        self.board=ServerBoard()
        self.hp=[100,100]
        self.max_hp=[100,100]
        self.shield=[0,0]
        self.color_scores=[[0]*7,[0]*7]
        self.starting_player=1-self.starting_player;self.turn=self.starting_player
        self.winner=None;self.move_number=0
        self.ability_slots=[0,0];self.ability_slots[self.starting_player]=1
        self.own_turn_count=[0,0];self.own_turn_count[self.starting_player]=1
        self.extra_turn_bank=[0,0]
        self.restart_ready=[False,False];self.restart_pending=False
        await self.broadcast({"event":"new_game","starting_player":self.starting_player})

    async def reset_after_leave(self):
        if self.player_count!=1:return
        remaining=next(s for s in self.sockets if s is not None)
        old_index=0 if self.sockets[0] is remaining else 1
        name=self.player_names[old_index]
        self.sockets=[remaining,None]
        self.board=ServerBoard()
        self.hp=[100,100]
        self.max_hp=[100,100]
        self.shield=[0,0]
        self.color_scores=[[0]*7,[0]*7]
        self.player_names=[name,"Player 2"];self.starting_player=0;self.turn=0;self.winner=None;self.move_number=0
        self.ability_slots=[1,0];self.own_turn_count=[1,0];self.extra_turn_bank=[0,0]
        self.restart_ready=[False,False];self.restart_pending=False
        await self.broadcast({"event":"player_left","you_are_now":0})
