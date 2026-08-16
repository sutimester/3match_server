import asyncio,json,random
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
        self.starting_player=random.randint(0,1);self.turn=self.starting_player;self.winner=None;self.move_number=0
        self.ability_used=[
            [False,False,False,False,False],
            [False,False,False,False,False],
        ]
        self.own_turn_count=[0,0];self.own_turn_count[self.starting_player]=1;self.extra_turn_bank=[0,0]
        self.restart_ready=[False,False];self.restart_pending=False
        self.action_log=[]

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
            "ability_used":self.ability_used,"own_turn_count":self.own_turn_count,"extra_turn_bank":self.extra_turn_bank,
            "restart_ready":self.restart_ready,"restart_pending":self.restart_pending,"move_number":self.move_number,
            "action_log":self.action_log,
            "rules_version":84,
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

    def _push_log(self,*lines):
        for line in lines:
            if line:
                self.action_log.append(str(line))
        self.action_log=self.action_log[-100:]

    def _format_removed(self,result):
        names=["red","green","blue","yellow","purple"]
        parts=[]

        chain_steps=result.get("cascade_color_points") or []
        if chain_steps:
            points=[
                sum(int(step[i]) for step in chain_steps)
                for i in range(7)
            ]
        else:
            points=result.get("color_points",[0]*7)

        for i,name in enumerate(names):
            count=int(points[i]) if i<len(points) else 0
            if count:
                parts.append(f"{count} {name}")

        gray=int(result.get("gray_removed",0))
        white=int(result.get("white_removed",0))

        if gray:
            parts.append(f"{gray} gray")
        if white:
            parts.append(f"{white} white")

        return ", ".join(parts) if parts else "no stones"

    def _format_chain_step(self,step):
        names=["red","green","blue","yellow","purple"]
        parts=[]

        points=step.get("color_points",[0]*7)
        for i,name in enumerate(names):
            count=int(points[i]) if i<len(points) else 0
            if count:
                parts.append(f"{count} {name}")

        gray=int(step.get("gray_removed",0))
        white=int(step.get("white_removed",0))

        if gray:
            parts.append(f"{gray} gray")
        if white:
            parts.append(f"{white} white")

        return ", ".join(parts) if parts else "no stones"

    def _chain_effect_text(self,result):
        steps=result.get("animation_steps",[])
        if len(steps)<=1:
            return []

        return [
            f"Chain {index}: {self._format_chain_step(step)}"
            for index,step in enumerate(steps[1:],start=1)
        ]

    def _make_result_log(self,p,result,shield_before_enemy,hp_before_enemy,shield_before_self):
        player_name=self.player_names[p]
        enemy=1-p

        removed=self._format_removed(result)
        line1=f"{player_name}: removed {removed}."

        effects=[]

        points=result.get("color_points",[0]*7)
        collectible=sum(int(points[i]) for i in range(min(5,len(points))))
        if collectible:
            effects.append(f"+{collectible} color points")

        shield_gain=max(0,self.shield[p]-shield_before_self)
        if shield_gain:
            effects.append(f"+{shield_gain} shield")

        shield_loss=max(0,shield_before_enemy-self.shield[enemy])
        hp_loss=max(0,hp_before_enemy-self.hp[enemy])

        if shield_loss:
            effects.append(f"{self.player_names[enemy]} shield -{shield_loss}")
        if hp_loss:
            effects.append(f"{self.player_names[enemy]} HP -{hp_loss}")

        if result.get("extra_turn"):
            effects.append("extra turn")

        if result.get("board_regenerated"):
            effects.append("new playable board generated")

        # Include exactly what disappeared in every cascade after the initial clear.
        effects.extend(
            self._chain_effect_text(result)
        )

        line2="Effect: "+(
            "; ".join(effects)
            if effects
            else "no HP/shield effect"
        )+"."

        return line1,line2

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

        # Award points from every clear in the complete chain.
        chain_steps=result.get("cascade_color_points") or []
        if chain_steps:
            points=[
                sum(int(step[i]) for step in chain_steps)
                for i in range(7)
            ]
        else:
            points=[int(v) for v in result.get("color_points",[0]*7)]

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
        # Once per normal own turn; unavailable during any extra turn.
        return not self.is_extra_turn[p]

    def ability_available(self,p,a):
        if p not in (0,1):return False,"invalid_player"
        if self.winner is not None:return False,"game_over"
        if self.player_count<2:return False,"waiting_for_opponent"
        if p!=self.turn:return False,"not_your_turn"
        if a not in (RED,GREEN,BLUE,YELLOW,PURPLE):return False,"invalid_ability"
        if self.color_scores[p][a]<ABILITY_COST:return False,"not_enough_points"
        if a==GREEN:
            return (
                (False,"hp_already_full")
                if self.hp[p]>=self.max_hp[p]
                else (True,None)
            )

        if self.ability_used[p][a]:
            return False,"ability_already_used_this_turn"

        if a==YELLOW and not self.yellow_available(p):
            return False,"yellow_not_available_this_turn"
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
            self.ability_used[p][PURPLE]=True

            result=self.board.clear_selected_color(target_color)
            if result is None:
                self.color_scores[p][PURPLE]+=ABILITY_COST
                self.ability_used[p][PURPLE]=False
                return {"ok":False,"reason":"invalid_purple_target"}

            # Purple uses the exact same scoring application as a board move.
            enemy=1-p
            shield_before_enemy=self.shield[enemy]
            hp_before_enemy=self.hp[enemy]
            shield_before_self=self.shield[p]

            self._apply_scoring_result(p,result)

            line1,line2=self._make_result_log(
                p,
                result,
                shield_before_enemy,
                hp_before_enemy,
                shield_before_self,
            )
            self._push_log(
                f"{self.player_names[p]} used PURPLE.",
                line1,
                line2,
            )

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
            self.ability_used[p][a]=True

            if a==RED:
                self.max_hp[o]=max(0,self.max_hp[o]-15)
                self.hp[o]=min(self.hp[o],self.max_hp[o])
                if self.hp[o]<=0:self.winner=p
            elif a==BLUE:self.max_hp[p]+=5
            elif a==YELLOW:self.extra_turn_bank[p]+=1

        ability_names={
            RED:"RED",
            GREEN:"GREEN",
            BLUE:"BLUE",
            YELLOW:"YELLOW",
        }

        if a==RED:
            self._push_log(
                f"{self.player_names[p]} used RED: {self.player_names[o]} max HP -15."
            )
        elif a==GREEN:
            self._push_log(
                f"{self.player_names[p]} used GREEN: healed up to +15 HP."
            )
        elif a==BLUE:
            self._push_log(
                f"{self.player_names[p]} used BLUE: max HP +5."
            )
        elif a==YELLOW:
            self._push_log(
                f"{self.player_names[p]} used YELLOW: gained an extra turn."
            )

        await self.broadcast({"event":"ability","ability_player":p,"ability":a})
        return {"ok":True}

    def _begin_turn(self,p,extra_turn=False):
        self.turn=p
        self.ability_used[p]=[
            False,False,False,False,False
        ]
        self.is_extra_turn=[False,False]
        self.is_extra_turn[p]=bool(extra_turn)
        if not extra_turn:
            self.own_turn_count[p]+=1

    def _resolve_next_turn(self,p,extra):
        if extra:self.extra_turn_bank[p]+=1
        if self.extra_turn_bank[p]>0:
            self.extra_turn_bank[p]-=1
            return (p,True)
        return (1-p,False)

    async def make_move(self,p,a,b):
        if self.winner is not None:return {"ok":False,"reason":"game_over"}
        if self.player_count<2:return {"ok":False,"reason":"waiting_for_opponent"}
        if p!=self.turn:return {"ok":False,"reason":"not_your_turn"}

        result=self.board.resolve_swap(a,b)
        if result is None:
            self._push_log(
                f"{self.player_names[p]}: invalid move - no match."
            )
            await self.broadcast({"event":"invalid","invalid_player":p})
            return {"ok":False,"reason":"no_match"}

        enemy=1-p
        shield_before_enemy=self.shield[enemy]
        hp_before_enemy=self.hp[enemy]
        shield_before_self=self.shield[p]

        # Exactly one authoritative scoring application.
        self._apply_scoring_result(p,result)

        line1,line2=self._make_result_log(
            p,
            result,
            shield_before_enemy,
            hp_before_enemy,
            shield_before_self,
        )
        self._push_log(line1,line2)

        self.move_number+=1

        if self.winner is None:
            next_player,is_extra=self._resolve_next_turn(p,result.get("extra_turn",False))
            self._begin_turn(next_player,is_extra)

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
        self.ability_used=[
            [False,False,False,False,False],
            [False,False,False,False,False],
        ]
        self.own_turn_count=[0,0];self.own_turn_count[self.starting_player]=1
        self.extra_turn_bank=[0,0]
        self.is_extra_turn=[False,False]
        self.restart_ready=[False,False]
        self.restart_pending=False
        self.action_log=[
            f"New game. {self.player_names[self.starting_player]} starts."
        ]
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
        self.player_names=[name,"Player 2"]
        self.starting_player=random.randint(0,1)
        self.turn=self.starting_player
        self.winner=None;self.move_number=0
        self.ability_used=[
            [False,False,False,False,False],
            [False,False,False,False,False],
        ]
        self.own_turn_count=[0,0]
        self.own_turn_count[self.starting_player]=1
        self.extra_turn_bank=[0,0]
        self.restart_ready=[False,False]
        self.restart_pending=False
        self.action_log=["Opponent left the match."]
        await self.broadcast({"event":"player_left","you_are_now":0})
