import asyncio,json,random

PLAYER_COLORS=[[241, 68, 79], [61, 190, 105], [67, 126, 241], [245, 207, 64], [183, 83, 222], [142, 149, 160], [250, 250, 250]]

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
        self.player_colors=[PLAYER_COLORS[0][:],PLAYER_COLORS[1][:]]
        self.player_color_random=[False,False]
        self.starting_player=random.randint(0,1);self.turn=self.starting_player;self.winner=None;self.move_number=0
        self.ability_used=[
            [False,False,False,False,False],
            [False,False,False,False,False],
        ]
        self.own_turn_count=[0,0];self.own_turn_count[self.starting_player]=1;self.extra_turn_bank=[0,0]
        self.is_extra_turn=[False,False]
        self.restart_ready=[False,False];self.restart_pending=False
        self.action_log=[]
        self.locked_cells=[None,None]
        self.lock_changed=[False,False]
        self.lock_age=[0,0]
        self.lock_refill_locked=[False,False]

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
            "player_names":self.player_names,"player_colors":self.player_colors,
            "starting_player":self.starting_player,
            "turn":self.turn,"winner":self.winner,"players":self.player_count,"spectators":self.spectator_count,
            "ability_used":self.ability_used,"own_turn_count":self.own_turn_count,"extra_turn_bank":self.extra_turn_bank,
            "is_extra_turn":self.is_extra_turn,
            "restart_ready":self.restart_ready,"restart_pending":self.restart_pending,"move_number":self.move_number,
            "action_log":self.action_log,
            "locked_cells":[list(x) if x is not None else None for x in self.locked_cells],
            "lock_changed":self.lock_changed,
            "lock_age":self.lock_age,
            "lock_refill_locked":self.lock_refill_locked,
            "rules_version":115,
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
            effects.append("NEW BOARD generated: no valid moves remained")

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

    def _reset_all_locks(self):
        self.locked_cells=[None,None]
        self.lock_changed=[False,False]
        self.lock_age=[0,0]
        self.lock_refill_locked=[False,False]

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

            if result.get("board_regenerated"):
                self._reset_all_locks()
                self._push_log(
                    "LOCKS RESET: new board generation removed all active locks."
                )

            # Purple is also the player's own clear. If it clears the
            # player's locked stone, the lock ends immediately.
            own_lock=self.locked_cells[p]
            if own_lock is not None and result.get("animation_steps"):
                own_lock_matched=any(
                    own_lock in {
                        tuple(x)
                        for x in step.get("matched",[])
                    }
                    for step in result["animation_steps"]
                )
                if own_lock_matched:
                    self.locked_cells[p]=None
                    self.lock_age[p]=0
                    self.lock_changed[p]=True
                    self.lock_refill_locked[p]=False
                    self._push_log(
                        f"{self.player_names[p]} lock removed by own match."
                    )

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

        # Lock aging/expiry is prepared before this playable turn starts.

        self.ability_used[p]=[
            False,False,False,False,False
        ]
        self.is_extra_turn=[False,False]
        self.is_extra_turn[p]=bool(extra_turn)
        self.lock_changed[p]=False
        self.lock_refill_locked[p]=False
        if not extra_turn:
            self.own_turn_count[p]+=1

    def _resolve_next_turn(self,p,extra):
        if extra:self.extra_turn_bank[p]+=1
        if self.extra_turn_bank[p]>0:
            self.extra_turn_bank[p]-=1
            return (p,True)
        return (1-p,False)

    async def set_color(self,p,color,random_choice=False):
        if p not in (0,1):
            return {"ok":False,"reason":"invalid_player"}

        self.player_color_random[p]=bool(random_choice)

        if self.player_color_random[p]:
            other=self.player_colors[1-p]
            choices=[c for c in PLAYER_COLORS if c!=other]
            self.player_colors[p]=random.choice(choices or PLAYER_COLORS)[:]
        else:
            try:
                color=[int(color[0]),int(color[1]),int(color[2])]
            except Exception:
                return {"ok":False,"reason":"invalid_color"}

            if color not in PLAYER_COLORS:
                return {"ok":False,"reason":"invalid_color"}

            self.player_colors[p]=color[:]

        await self.broadcast({
            "event":"player_color",
            "color_player":p,
            "color":self.player_colors[p],
        })
        return {"ok":True}

    async def set_lock(self,p,cell):
        if self.winner is not None:
            return {"ok":False,"reason":"game_over"}
        if self.player_count<2:
            return {"ok":False,"reason":"waiting_for_opponent"}
        if p!=self.turn:
            return {"ok":False,"reason":"not_your_turn"}
        if self.lock_refill_locked[p]:
            return {"ok":False,"reason":"lock_refill_already_happened"}

        try:
            cell=(int(cell[0]),int(cell[1]))
        except Exception:
            return {"ok":False,"reason":"invalid_cell"}

        if not self.board.in_bounds(cell):
            return {"ok":False,"reason":"invalid_cell"}

        if self.board.grid[cell[0]][cell[1]] is None:
            return {"ok":False,"reason":"cannot_lock_empty_space"}

        other=1-p
        if self.locked_cells[other]==cell:
            return {"ok":False,"reason":"stone_already_locked"}

        old=self.locked_cells[p]
        if old==cell:
            self.locked_cells[p]=None
            self.lock_age[p]=0
        else:
            self.locked_cells[p]=cell
            self.lock_age[p]=0
        self.lock_changed[p]=True

        filled=0
        new_lock=self.locked_cells[p]

        if old is not None and old!=new_lock:
            anchors={
                x
                for x in self.locked_cells
                if x is not None
            }
            filled,refill_step=self.board.refill_after_lock_change(
                anchors,
                record_step=True,
            )

        cleanup_steps=[]
        if filled>0:
            self.lock_refill_locked[p]=True
            self._push_log(
                f"{self.player_names[p]} lock release refilled {filled} empty board spaces."
            )

            cleanup=self.board.resolve_refill_matches(
                anchored_cells=anchors,
                record_steps=True,
            )
            cleanup_steps=cleanup.get("animation_steps",[])

            if cleanup_steps:
                self._push_log(
                    f"REFILL CLEANUP: {cleanup.get('removed',0)} stones cleared automatically with no score."
                )

            if cleanup.get("board_regenerated"):
                self._reset_all_locks()
                self._push_log(
                    "NEW BOARD: refill cleanup left no valid moves; locks reset."
                )

        action="UNLOCKED" if old==cell else "LOCKED"
        self._push_log(
            f"{self.player_names[p]} {action} stone at {cell[0]+1},{cell[1]+1}."
        )
        await self.broadcast({
            "event":"lock",
            "lock_player":p,
            "lock_refilled":filled,
            "board":self.board.grid,
            "refill_step":refill_step if filled>0 else None,
            "cleanup_steps":cleanup_steps,
        })
        return {"ok":True}

    def _prepare_lock_before_turn(self,p):
        """Advance or expire p's lock immediately before p's own turn."""
        if p not in (0,1) or self.locked_cells[p] is None:
            return 0,None,False

        if self.lock_age[p]<1:
            self.lock_age[p]=1
            return 0,None,False

        self.locked_cells[p]=None
        self.lock_age[p]=0

        anchors={
            x
            for x in self.locked_cells
            if x is not None
        }
        filled,step=self.board.refill_after_lock_change(
            anchors,
            record_step=True,
        )

        self._push_log(
            f"{self.player_names[p]} lock expired before turn."
        )
        cleanup_steps=[]
        if filled>0:
            self._push_log(
                f"Lock expiry refilled {filled} empty board spaces before turn."
            )

            cleanup=self.board.resolve_refill_matches(
                anchored_cells=anchors,
                record_steps=True,
            )
            cleanup_steps=cleanup.get("animation_steps",[])

            if cleanup_steps:
                self._push_log(
                    f"REFILL CLEANUP: {cleanup.get('removed',0)} stones cleared automatically with no score."
                )

            if cleanup.get("board_regenerated"):
                self._reset_all_locks()
                self._push_log(
                    "NEW BOARD: refill cleanup left no valid moves; locks reset."
                )

        return filled,step,True,cleanup_steps


    async def make_move(self,p,a,b):
        if self.winner is not None:return {"ok":False,"reason":"game_over"}
        if self.player_count<2:return {"ok":False,"reason":"waiting_for_opponent"}
        if p!=self.turn:return {"ok":False,"reason":"not_your_turn"}

        result=self.board.resolve_swap(
            a,b,
            opponent_lock=self.locked_cells[1-p],
            own_lock=self.locked_cells[p],
        )
        if result is None:
            self._push_log(
                f"{self.player_names[p]}: invalid move - no match."
            )
            await self.broadcast({"event":"invalid","invalid_player":p})
            return {"ok":False,"reason":"no_match"}

        if result.get("board_regenerated"):
            self._reset_all_locks()
            self._push_log(
                "LOCKS RESET: new board generation removed all active locks."
            )

        own_lock=self.locked_cells[p]
        if own_lock is not None and result.get("animation_steps"):
            own_lock_matched=any(
                own_lock in {
                    tuple(x)
                    for x in step.get("matched",[])
                }
                for step in result["animation_steps"]
            )
            if own_lock_matched:
                self.locked_cells[p]=None
                self.lock_age[p]=0
                self.lock_changed[p]=True
                self.lock_refill_locked[p]=False
                self._push_log(
                    f"{self.player_names[p]} lock removed by own match."
                )

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

        lock_expire_filled=0
        lock_expire_step=None
        lock_expired=False
        lock_cleanup_steps=[]
        next_player=None
        is_extra=False

        if self.winner is None:
            next_player,is_extra=self._resolve_next_turn(
                p,
                result.get("extra_turn",False),
            )

            lock_expire_filled,lock_expire_step,lock_expired,lock_cleanup_steps=(
                self._prepare_lock_before_turn(next_player)
            )

            self._begin_turn(next_player,is_extra)

        payload=dict(result)

        if lock_expire_step is not None:
            payload["animation_steps"]=list(
                result.get("animation_steps",[])
            )+[lock_expire_step]+list(lock_cleanup_steps)

        payload.update({
            "event":"move",
            "mover":p,
            "move_a":list(a),
            "move_b":list(b),
            "awarded_color_points":result["color_points"],
            "lock_expired":lock_expired,
            "lock_expire_refilled":lock_expire_filled,
            "prepared_turn_player":next_player,
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

        for p in (0,1):
            if self.player_color_random[p]:
                other=self.player_colors[1-p]
                choices=[c for c in PLAYER_COLORS if c!=other]
                self.player_colors[p]=random.choice(choices or PLAYER_COLORS)[:]

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
        self.locked_cells=[None,None]
        self.lock_changed=[False,False]
        self.lock_age=[0,0]
        self.lock_refill_locked=[False,False]
        self.restart_ready=[False,False]
        self.restart_pending=False
        self.action_log=[
            "NEW BOARD: a fresh board was generated for the new game.",
            f"New game. {self.player_names[self.starting_player]} starts.",
        ]
        await self.broadcast({
            "event":"new_game",
            "starting_player":self.starting_player,
            "board":self.board.grid,
        })

    async def reset_after_leave(self):
        if self.player_count!=1:return
        remaining=next(s for s in self.sockets if s is not None)
        old_index=0 if self.sockets[0] is remaining else 1
        name=self.player_names[old_index]
        kept_color=self.player_colors[old_index][:]
        kept_random=self.player_color_random[old_index]
        self.sockets=[remaining,None]
        self.board=ServerBoard()
        self.hp=[100,100]
        self.max_hp=[100,100]
        self.shield=[0,0]
        self.color_scores=[[0]*7,[0]*7]
        self.player_names=[name,"Player 2"]
        self.player_colors=[kept_color,PLAYER_COLORS[1][:]]
        self.player_color_random=[kept_random,False]
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
        self.is_extra_turn=[False,False]
        self.locked_cells=[None,None]
        self.lock_changed=[False,False]
        self.lock_age=[0,0]
        self.lock_refill_locked=[False,False]
        self.restart_ready=[False,False]
        self.restart_pending=False
        self.action_log=["Opponent left the match."]
        await self.broadcast({"event":"player_left","you_are_now":0})
