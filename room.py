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
        self.code=code
        self.public=public
        self.display_name=display_name
        self.sockets=[None,None]
        # Spectators are completely separate from the two player slots.
        self.spectators=[]
        self.board=ServerBoard()
        self.hp=[100,100]
        self.max_hp=[100,100]
        self.color_scores=[[0]*6,[0]*6]
        self.player_names=["Player 1","Player 2"]
        self.starting_player=0
        self.turn=self.starting_player
        self.winner=None
        self.move_number=0
        self.ability_slots=[0,0]
        self.ability_slots[self.starting_player]=1
        self.own_turn_count=[0,0]
        self.own_turn_count[self.starting_player]=1
        self.extra_turn_bank=[0,0]
        self.restart_ready=[False,False]
        self.restart_pending=False

    @property
    def player_count(self):return sum(1 for s in self.sockets if s is not None)
    @property
    def is_full(self):return self.player_count>=2
    @property
    def is_empty(self):
        return self.player_count==0 and len(self.spectators)==0

    @property
    def spectator_count(self):
        return len(self.spectators)

    @property
    def is_live(self):
        return self.public and self.player_count==2 and self.winner is None

    def public_info(self):
        return {
            "code":self.code,
            "name":self.display_name or self.code,
            "players":self.player_count,
            "spectators":self.spectator_count,
            "open":not self.is_full,
            "live":self.is_live,
        }

    def add_socket(self,socket):
        for i,s in enumerate(self.sockets):
            if s is None:self.sockets[i]=socket;return i
        return None

    def remove_socket(self,socket):
        for i,s in enumerate(self.sockets):
            if s is socket:
                self.sockets[i]=None
                return i
        return None

    def add_spectator(self,socket):
        if socket not in self.spectators:
            self.spectators.append(socket)

    def remove_spectator(self,socket):
        if socket in self.spectators:
            self.spectators.remove(socket)
            return True
        return False

    def state_payload(self,extra=None):
        data={
            "type":"state","room":self.code,"room_name":self.display_name or self.code,"public":self.public,
            "board":self.board.grid,"hp":self.hp,"max_hp":self.max_hp,"color_scores":self.color_scores,
            "player_names":self.player_names,"turn":self.turn,"winner":self.winner,"players":self.player_count,"spectators":self.spectator_count,
            "ability_slots":self.ability_slots,"own_turn_count":self.own_turn_count,"extra_turn_bank":self.extra_turn_bank,
            "restart_ready":self.restart_ready,"restart_pending":self.restart_pending,"move_number":self.move_number,
            "rules_version":45,
        }
        if extra:data.update(extra)
        return data

    async def broadcast(self,extra=None):
        raw=json.dumps(self.state_payload(extra))

        for s in list(self.sockets):
            if s is not None:
                try:
                    await s.send(raw)
                except Exception:
                    self.remove_socket(s)

        for s in list(self.spectators):
            try:
                await s.send(raw)
            except Exception:
                self.remove_spectator(s)

    async def set_player_name(self,player,name):
        name=str(name or "").strip()[:20] or f"Player {player+1}"
        self.player_names[player]=name
        await self.broadcast({"event":"player_name","name_player":player,"name":name})

    def yellow_available(self,p):
        return self.own_turn_count[p] > 0 and self.own_turn_count[p] % 2 == 0

    def ability_available(self,p,a):
        if p not in (0,1):return False,"invalid_player"
        if self.winner is not None:return False,"game_over"
        if self.player_count<2:return False,"waiting_for_opponent"
        if p!=self.turn:return False,"not_your_turn"
        if a not in (RED,GREEN,BLUE,YELLOW,PURPLE):return False,"invalid_ability"
        if self.color_scores[p][a] < ABILITY_COST:return False,"not_enough_points"
        if a==GREEN:
            return (False,"hp_already_full") if self.hp[p]>=self.max_hp[p] else (True,None)
        if self.ability_slots[p]<=0:return False,"ability_limit_reached"
        if a==YELLOW and not self.yellow_available(p):return False,"yellow_not_available_this_turn"
        return True,None

    async def use_ability(self,p,a,target_color=None):
        ok,reason=self.ability_available(p,a)
        if not ok:return {"ok":False,"reason":reason}
        o=1-p
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
            elif a==YELLOW:
                self.extra_turn_bank[p]+=1

            elif a==PURPLE:
                # Purple clears every stone of one player-selected non-gray color.
                try:
                    target_color=int(target_color)
                except Exception:
                    # Refund because the target is invalid.
                    self.color_scores[p][a]+=ABILITY_COST
                    self.ability_slots[p]+=1
                    return {"ok":False,"reason":"purple_target_required"}

                if target_color < 0 or target_color >= 5:
                    self.color_scores[p][a]+=ABILITY_COST
                    self.ability_slots[p]+=1
                    return {"ok":False,"reason":"invalid_purple_target"}

                result=self.board.clear_selected_color(target_color)
                if result is None:
                    self.color_scores[p][a]+=ABILITY_COST
                    self.ability_slots[p]+=1
                    return {"ok":False,"reason":"invalid_purple_target"}

                o=1-p
                for i,v in enumerate(result["color_points"]):
                    self.color_scores[p][i]+=v

                self.hp[o]=max(0,self.hp[o]-result["damage"])
                if self.hp[o]<=0:
                    self.winner=p

                payload={
                    "event":"ability",
                    "ability_player":p,
                    "ability":a,
                    "target_color":target_color,
                    "animation_steps":result["animation_steps"],
                    "specials":result["specials"],
                    "board_regenerated":result["board_regenerated"],
                }
                await self.broadcast(payload)
                return {"ok":True}

        await self.broadcast({"event":"ability","ability_player":p,"ability":a})
        return {"ok":True}

    def _begin_turn(self,p):
        self.turn=p
        self.ability_slots=[0,0]
        self.ability_slots[p]=1
        self.own_turn_count[p]+=1

    def _resolve_next_turn(self,p,board_extra):
        if board_extra:self.extra_turn_bank[p]+=1
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

        o=1-p
        for i,v in enumerate(result["color_points"]):self.color_scores[p][i]+=v
        self.hp[o]=max(0,self.hp[o]-result["damage"])
        self.move_number+=1

        if self.hp[o]<=0:self.winner=p
        else:self._begin_turn(self._resolve_next_turn(p,result.get("extra_turn",False)))

        result.update({"event":"move","mover":p})
        await self.broadcast(result)
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
        if self.player_count<2 or not all(self.restart_ready):self.restart_pending=False;return
        self.board=ServerBoard()
        self.hp=[100,100]
        self.max_hp=[100,100]
        self.color_scores=[[0]*6,[0]*6]

        # Every rematch starts with the player who did NOT start
        # the previous match.
        self.starting_player=1-self.starting_player
        self.turn=self.starting_player
        self.winner=None
        self.move_number=0

        self.ability_slots=[0,0]
        self.ability_slots[self.starting_player]=1
        self.own_turn_count=[0,0]
        self.own_turn_count[self.starting_player]=1
        self.extra_turn_bank=[0,0]

        self.restart_ready=[False,False]
        self.restart_pending=False

        await self.broadcast({
            "event":"new_game",
            "starting_player":self.starting_player,
        })

    async def reset_after_leave(self):
        if self.player_count!=1:return
        remaining=next(s for s in self.sockets if s is not None)
        remaining_name=self.player_names[0] if self.sockets[0] is remaining else self.player_names[1]
        self.sockets=[remaining,None]
        self.board=ServerBoard()
        self.hp=[100,100];self.max_hp=[100,100];self.color_scores=[[0]*6,[0]*6]
        self.player_names=[remaining_name,"Player 2"]
        self.starting_player=0
        self.turn=self.starting_player
        self.winner=None
        self.move_number=0

        self.ability_slots=[1,0]
        self.own_turn_count=[1,0]
        self.extra_turn_bank=[0,0]

        self.restart_ready=[False,False]
        self.restart_pending=False
        await self.broadcast({"event":"player_left","you_are_now":0})
