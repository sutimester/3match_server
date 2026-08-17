import random
ROWS=8
COLS=8
GRAY=5
WHITE_STONE=6
GRAY_DAMAGE=10
WHITE_SHIELD_GAIN=10

COLOR_COUNT=7

GRAY4=7
GRAY5=8
GRAY6=9
WHITE4=10
WHITE5=11
WHITE6=12
MULTICOLOR=13

def base_color(value):
    if value in (GRAY4,GRAY5,GRAY6):
        return GRAY
    if value in (WHITE4,WHITE5,WHITE6):
        return WHITE_STONE
    return value

def special_number(value):
    if value in (GRAY4,WHITE4):
        return 4
    if value in (GRAY5,WHITE5):
        return 5
    if value in (GRAY6,WHITE6):
        return 6
    return None

def make_numbered_special(color,length):
    length=max(4,min(6,int(length)))
    if color==GRAY:
        return {4:GRAY4,5:GRAY5,6:GRAY6}[length]
    if color==WHITE_STONE:
        return {4:WHITE4,5:WHITE5,6:WHITE6}[length]
    return color

class ServerBoard:
    def __init__(self):
        self.grid=[[0]*COLS for _ in range(ROWS)]
        self.regenerate_playable()

    def clone(self):
        other=ServerBoard.__new__(ServerBoard)
        other.grid=[row[:] for row in self.grid]
        return other

    @staticmethod
    def in_bounds(cell):
        return (
            isinstance(cell,tuple) and len(cell)==2
            and isinstance(cell[0],int) and isinstance(cell[1],int)
            and 0<=cell[0]<ROWS and 0<=cell[1]<COLS
        )

    @staticmethod
    def adjacent(a,b):
        return (
            ServerBoard.in_bounds(a) and ServerBoard.in_bounds(b)
            and abs(a[0]-b[0])+abs(a[1]-b[1])==1
        )

    def load(self,grid):
        self.grid=[row[:] for row in grid]

    def swap(self,a,b):
        r1,c1=a;r2,c2=b
        self.grid[r1][c1],self.grid[r2][c2]=self.grid[r2][c2],self.grid[r1][c1]

    def _creates_start_match(self,r,c):
        v=self.grid[r][c]
        return (
            c>=2
            and base_color(self.grid[r][c-1])==base_color(v)
            and base_color(self.grid[r][c-2])==base_color(v)
        ) or (
            r>=2
            and base_color(self.grid[r-1][c])==base_color(v)
            and base_color(self.grid[r-2][c])==base_color(v)
        )

    def _generate_without_matches(self):
        self.grid=[[0]*COLS for _ in range(ROWS)]
        for r in range(ROWS):
            for c in range(COLS):
                values=list(range(COLOR_COUNT))
                random.shuffle(values)
                for v in values:
                    self.grid[r][c]=v
                    if not self._creates_start_match(r,c):
                        break

    def regenerate_playable(self):
        while True:
            self._generate_without_matches()
            if not self.collect_runs() and self.has_valid_move():
                return

    def collect_runs(self,blocked_cells=None):
        blocked=set(blocked_cells or [])
        runs=[]

        def value_at(r,c):
            if (r,c) in blocked:
                return None
            return base_color(self.grid[r][c])

        for r in range(ROWS):
            s=0
            while s<COLS:
                v=value_at(r,s)
                e=s+1
                while e<COLS and value_at(r,e)==v:
                    e+=1
                if v is not None and e-s>=3:
                    runs.append({
                        "dir":"h",
                        "value":v,
                        "cells":[(r,c) for c in range(s,e)],
                    })
                s=e

        for c in range(COLS):
            s=0
            while s<ROWS:
                v=value_at(s,c)
                e=s+1
                while e<ROWS and value_at(e,c)==v:
                    e+=1
                if v is not None and e-s>=3:
                    runs.append({
                        "dir":"v",
                        "value":v,
                        "cells":[(r,c) for r in range(s,e)],
                    })
                s=e

        return runs


    def _direct_move_creates_match(
        self,
        a,
        b,
        opponent_lock=None,
        own_lock=None,
    ):
        if not self.adjacent(a,b):
            return False

        anchors={x for x in (opponent_lock,own_lock) if x is not None}
        if a in anchors or b in anchors:
            return False

        ar,ac=a; br,bc=b
        raw_a=self.grid[ar][ac]
        raw_b=self.grid[br][bc]

        joker_after=None
        if raw_a==MULTICOLOR:
            joker_after=b
        elif raw_b==MULTICOLOR:
            joker_after=a

        self.swap(a,b)

        def initial_runs_for(blocked):
            if joker_after is None:
                return self.collect_runs(blocked)

            jr,jc=joker_after
            choices=[]
            for color in range(5):
                self.grid[jr][jc]=color
                cruns=self.collect_runs(blocked)
                participating=[
                    run for run in cruns
                    if joker_after in run["cells"]
                    and run["value"]==color
                ]
                if participating:
                    choices.append(cruns)
            return choices[0] if choices else []

        blocked={opponent_lock} if opponent_lock is not None else set()
        runs=initial_runs_for(blocked)

        self.grid[ar][ac]=raw_a
        self.grid[br][bc]=raw_b
        return bool(runs)

    def has_valid_move(self,opponent_lock=None,own_lock=None):
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0]>=ROWS or b[1]>=COLS:
                        continue
                    if self._direct_move_creates_match(
                        (r,c),b,opponent_lock,own_lock
                    ):
                        return True
        return False

    def valid_moves(self,opponent_lock=None,own_lock=None):
        out=[]
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0]>=ROWS or b[1]>=COLS:
                        continue
                    a=(r,c)
                    if self._direct_move_creates_match(
                        a,b,opponent_lock,own_lock
                    ):
                        sim=self.clone()
                        result=sim.resolve_swap(
                            a,b,
                            record_steps=False,
                            opponent_lock=opponent_lock,
                            own_lock=own_lock,
                        )
                        if result is not None:
                            out.append((a,b,result))
        return out


    def _detect_t5(self,runs):
        """
        Detect a T made from exactly five normal colored stones in any of
        the four orientations: up, down, left or right.

        It consists of one horizontal 3-run and one vertical 3-run of the
        same color. Their single intersection must be the middle of one run
        and an endpoint of the other. This excludes + shapes.

        Called only for the player's direct swap, never for cascades.
        """
        horizontals=[
            run for run in runs
            if run["dir"]=="h"
            and len(run["cells"])==3
            and run["value"] in range(5)
        ]
        verticals=[
            run for run in runs
            if run["dir"]=="v"
            and len(run["cells"])==3
            and run["value"] in range(5)
        ]

        for h in horizontals:
            for v in verticals:
                if v["value"]!=h["value"]:
                    continue

                common=set(h["cells"]) & set(v["cells"])
                if len(common)!=1:
                    continue

                intersection=next(iter(common))
                union=set(h["cells"]) | set(v["cells"])

                if len(union)!=5:
                    continue

                h_mid=h["cells"][1]
                v_mid=v["cells"][1]
                h_end=intersection in (h["cells"][0],h["cells"][-1])
                v_end=intersection in (v["cells"][0],v["cells"][-1])

                # Up/down T: middle of horizontal bar + endpoint of vertical stem.
                vertical_t=(intersection==h_mid and v_end)

                # Left/right T: endpoint of horizontal stem + middle of vertical bar.
                horizontal_t=(h_end and intersection==v_mid)

                if not (vertical_t or horizontal_t):
                    continue

                return {
                    "cells":union,
                    "intersection":intersection,
                    "value":h["value"],
                }

        return None

    def _expand_specials(self,runs,preferred_special_cell=None):
        matched=set()
        specials=[]

        for run in runs:
            cells=run["cells"]
            value=run["value"]
            n=len(cells)
            matched.update(cells)

            # Gray/white 4+ never expands into row/column/full-color clears.
            # It creates a numbered stone of the same base color instead.
            if value in (GRAY,WHITE_STONE) and n>=4:
                number=min(6,n)
                if preferred_special_cell in cells:
                    target=preferred_special_cell
                else:
                    target=cells[len(cells)//2]
                specials.append({
                    "kind":"numbered_special",
                    "value":value,
                    "number":number,
                    "cell":list(target),
                })
                continue

            if n>=6:
                matched.update(
                    (r,c)
                    for r in range(ROWS)
                    for c in range(COLS)
                    if base_color(self.grid[r][c])==value
                )
                specials.append({"kind":"color_clear","value":value,"length":n})

            elif n==5:
                mr,mc=cells[len(cells)//2]
                matched.update((mr,c) for c in range(COLS))
                matched.update((r,mc) for r in range(ROWS))
                specials.append({"kind":"cross_clear","row":mr,"column":mc})

            elif n==4:
                if run["dir"]=="h":
                    row=cells[0][0]
                    matched.update((row,c) for c in range(COLS))
                    specials.append({"kind":"row_clear","index":row})
                else:
                    col=cells[0][1]
                    matched.update((r,col) for r in range(ROWS))
                    specials.append({"kind":"column_clear","index":col})

        return matched,specials

    def _collapse(self,anchored_cells=None,fill_released=False):
        """
        Gravity with locked stones as hard barriers.

        Normal clear/cascade:
        - region above the first lock can receive new stones from the top,
        - regions below a lock compact existing stones only,
        - missing cells below a lock remain None.

        fill_released is retained for compatibility, but lock-release
        refill uses the current barriers and never fills through an active lock.
        """
        anchors=set(anchored_cells or [])
        filled_new=0

        for c in range(COLS):
            anchor_rows=sorted(
                r for r in range(ROWS)
                if (r,c) in anchors
            )
            boundaries=[-1]+anchor_rows+[ROWS]

            for region_i in range(len(boundaries)-1):
                lo=boundaries[region_i]+1
                hi=boundaries[region_i+1]
                if lo>=hi:
                    continue

                survivors=[
                    self.grid[r][c]
                    for r in range(lo,hi)
                    if self.grid[r][c] is not None
                ]

                missing=(hi-lo)-len(survivors)

                # Only the topmost region has a natural supply from above.
                # During an explicit lock-release refill, regions which are no
                # longer protected by a lock are also filled.
                can_spawn = (region_i==0) or fill_released

                if can_spawn:
                    spawned=[
                        random.randrange(COLOR_COUNT)
                        for _ in range(missing)
                    ]
                    filled_new += missing
                else:
                    spawned=[None]*missing

                values=spawned+survivors

                for offset,r in enumerate(range(lo,hi)):
                    self.grid[r][c]=values[offset]

        return filled_new

    def refill_after_lock_change(self,anchored_cells=None,record_step=False):
        """
        Re-apply gravity after a lock is removed or moved.

        Returns an int by default for backward compatibility.
        With record_step=True returns (filled_count, animation_step).
        """
        before=[row[:] for row in self.grid] if record_step else None

        # Refill only regions that are reachable from the top with the
        # CURRENT locks in place. Areas below any still-active lock remain empty.
        filled=self._collapse(
            anchored_cells=anchored_cells,
            fill_released=False,
        )

        if not record_step:
            return filled

        step=None
        if filled>0:
            step={
                "before":before,
                "after":[row[:] for row in self.grid],
                "matched":[],
                "color_points":[0]*COLOR_COUNT,
                "gray_removed":0,
                "white_removed":0,
                "gray_value":0,
                "white_value":0,
                "specials":[],
                "anchored_cells":[
                    list(cell)
                    for cell in sorted(set(anchored_cells or []))
                ],
                "refill_only":True,
            }

        return filled,step


    def _score_cells(self,cells):
        """
        Unified scoring/effects. Numbered gray/white stones have weighted value:
        4 -> 40, 5 -> 50, 6 -> 60.
        """
        points=[0]*COLOR_COUNT
        gray_removed=0
        white_removed=0
        gray_value=0
        white_value=0
        removed=0

        for r,c in set(cells):
            raw=self.grid[r][c]
            if raw is None:
                continue

            removed+=1
            v=base_color(raw)
            number=special_number(raw)

            if v==GRAY:
                gray_removed+=1
                gray_value+=(number*10 if number else 10)
            elif v==WHITE_STONE:
                white_removed+=1
                white_value+=(number*10 if number else 10)
            else:
                points[v]+=1

        return points,gray_removed,white_removed,removed,gray_value,white_value

    @staticmethod
    def _add_points(total,step):
        for i,v in enumerate(step):
            total[i]+=v

    def _clear_cells(self,matched,record_steps,specials=None,anchored_cells=None):
        before=[row[:] for row in self.grid] if record_steps else None
        (
            step_points,gray_removed,white_removed,removed,gray_value,white_value
        )=self._score_cells(matched)

        # A directly activated multicolor joker counts as 5 stones of the
        # color it matched. _score_cells() already counted its temporary
        # target-color representation as 1, so add the remaining +4 here.
        for sp in (specials or []):
            if sp.get("kind")=="multicolor_used":
                value=sp.get("value")
                cell=tuple(sp.get("cell",(-1,-1)))
                if value in range(5) and cell in matched:
                    step_points[value]+=4

        creations=[]
        for sp in (specials or []):
            if sp.get("kind")=="numbered_special":
                creations.append((
                    tuple(sp["cell"]),
                    make_numbered_special(sp["value"],sp["number"]),
                ))
            elif sp.get("kind")=="multicolor_t5":
                creations.append((
                    tuple(sp["cell"]),
                    MULTICOLOR,
                ))

        for r,c in matched:
            self.grid[r][c]=None

        # The matched stone at the creation cell is fully scored as removed,
        # then replaced by the new numbered stone at that swap/match position.
        for (r,c),value in creations:
            self.grid[r][c]=value

        remaining_anchors=set(anchored_cells or [])-set(matched)
        self._collapse(remaining_anchors,fill_released=False)

        step=None
        if record_steps:
            step={
                "before":before,
                "matched":[list(x) for x in sorted(matched)],
                "after":[row[:] for row in self.grid],
                "color_points":step_points[:],
                "gray_removed":gray_removed,
                "white_removed":white_removed,
                "gray_value":gray_value,
                "white_value":white_value,
                "specials":list(specials or []),
                "anchored_cells":[
                    list(cell)
                    for cell in sorted(set(anchored_cells or []))
                    if cell not in set(matched)
                ],
            }

        return (
            step_points,gray_removed,white_removed,removed,step,gray_value,white_value
        )

    def _resolve_after_initial_clear(
        self,
        initial_matched,
        initial_specials,
        record_steps=True,
        initial_counts_as_match=False,
        cascade_blocked=None,
        anchored_cells=None,
    ):
        total_points=[0]*COLOR_COUNT
        cascade_points=[]
        total_gray=0
        total_white=0
        total_removed=0
        total_gray_value=0
        total_white_value=0
        specials=list(initial_specials or [])
        steps=[]
        cascade=0
        extra_turn=False

        p,g,w,n,step,gv,wv=self._clear_cells(initial_matched,record_steps,initial_specials,anchored_cells)
        self._add_points(total_points,p)
        cascade_points.append(p)
        total_gray+=g
        total_white+=w
        total_removed+=n
        total_gray_value+=gv
        total_white_value+=wv
        if step:steps.append(step)

        active_anchors=set(anchored_cells or [])-set(initial_matched)
        runs=self.collect_runs(active_anchors)
        while runs:
            cascade+=1

            if any(len(run["cells"])>=4 for run in runs):
                extra_turn=True

            matched,new_specials=self._expand_specials(runs)
            matched-=active_anchors
            specials.extend(new_specials)

            p,g,w,n,step,gv,wv=self._clear_cells(matched,record_steps,new_specials,active_anchors)
            self._add_points(total_points,p)
            cascade_points.append(p)
            total_gray+=g
            total_white+=w
            total_removed+=n
            total_gray_value+=gv
            total_white_value+=wv
            if step:steps.append(step)

            active_anchors-=set(matched)
            runs=self.collect_runs(active_anchors)

        regenerated=False
        if not self.has_valid_move():
            self.regenerate_playable()
            regenerated=True

        # Rebuild the awarded color totals from every cascade step.
        # This guarantees that chain reactions belong to the player who made
        # the original move and no later cascade can be omitted.
        if cascade_points:
            total_points=[
                sum(step[i] for step in cascade_points)
                for i in range(7)
            ]

        return {
            "color_points":total_points,
            "cascade_color_points":cascade_points,
            "gray_removed":total_gray,
            "white_removed":total_white,
            "damage":total_gray_value,
            "shield_gain":total_white_value,
            "gray_value":total_gray_value,
            "white_value":total_white_value,
            "removed":total_removed,
            "cascade":cascade,
            "specials":specials,
            "animation_steps":steps,
            "extra_turn":extra_turn,
            "board_regenerated":regenerated,
        }

    def resolve_swap(self,a,b,record_steps=True,opponent_lock=None,own_lock=None):
        if not self.adjacent(a,b):
            return None

        anchors={x for x in (opponent_lock,own_lock) if x is not None}
        if a in anchors or b in anchors:
            return None

        ar,ac=a
        br,bc=b
        raw_a=self.grid[ar][ac]
        raw_b=self.grid[br][bc]

        joker_after=None
        if raw_a==MULTICOLOR:
            joker_after=b
        elif raw_b==MULTICOLOR:
            joker_after=a

        self.swap(a,b)

        wildcard_move=joker_after is not None
        wildcard_target=None
        runs=None

        if wildcard_move:
            # Directly moved joker: test all five normal colors.
            # It may never represent gray or white.
            jr,jc=joker_after
            candidate_results=[]

            for color in range(5):
                self.grid[jr][jc]=color
                color_runs=self.collect_runs({opponent_lock} if opponent_lock is not None else set())

                participating=[
                    run for run in color_runs
                    if joker_after in run["cells"]
                    and run["value"]==color
                ]

                if participating:
                    # Prefer the color producing the largest direct match.
                    value=sum(len(run["cells"]) for run in participating)
                    candidate_results.append(
                        (value,color,color_runs)
                    )

            if not candidate_results:
                self.grid[ar][ac]=raw_a
                self.grid[br][bc]=raw_b
                return None

            candidate_results.sort(
                key=lambda item:item[0],
                reverse=True,
            )
            _value,wildcard_target,runs=candidate_results[0]
            self.grid[jr][jc]=wildcard_target

        else:
            runs=self.collect_runs({opponent_lock} if opponent_lock is not None else set())

        if not runs:
            self.grid[ar][ac]=raw_a
            self.grid[br][bc]=raw_b
            return None

        # T5 is checked ONLY for this direct move; cascades cannot create joker.
        t5=self._detect_t5(runs)

        if t5 is not None:
            matched=set(t5["cells"])
            if opponent_lock is not None: matched.discard(opponent_lock)
            intersection=t5["intersection"]
            specials=[{
                "kind":"multicolor_t5",
                "value":t5["value"],
                "cell":list(intersection),
            }]
            initial_extra=True
        else:
            initial_extra=any(
                len(run["cells"])>3
                for run in runs
                if not wildcard_move or joker_after in run["cells"]
            )

            preferred=None
            for candidate in (b,a):
                if any(candidate in run["cells"] for run in runs):
                    preferred=candidate
                    break

            matched,specials=self._expand_specials(
                runs,
                preferred_special_cell=preferred,
            )

        direct_run_cells=set()
        for run in runs:
            direct_run_cells.update(run["cells"])

        protected=set()
        if opponent_lock is not None:
            protected.add(opponent_lock)
        if own_lock is not None and own_lock not in direct_run_cells:
            protected.add(own_lock)
        matched-=protected

        if wildcard_move:
            specials.append({
                "kind":"multicolor_used",
                "value":wildcard_target,
                "cell":list(joker_after),
            })

        result=self._resolve_after_initial_clear(
            matched,
            specials,
            record_steps=record_steps,
            initial_counts_as_match=True,
            cascade_blocked=anchors,
            anchored_cells=anchors,
        )

        if initial_extra:
            result["extra_turn"]=True

        return result


    def clear_selected_color(self,value,record_steps=True):
        if not isinstance(value,int) or value<0 or value>=GRAY:
            return None

        matched={
            (r,c)
            for r in range(ROWS)
            for c in range(COLS)
            if base_color(self.grid[r][c])==value
        }

        if not matched:
            return {
                "color_points":[0]*COLOR_COUNT,
                "cascade_color_points":[],
                "gray_removed":0,
                "white_removed":0,
                "damage":0,
                "shield_gain":0,
                "gray_value":0,
                "white_value":0,
                "removed":0,
                "cascade":0,
                "specials":[{"kind":"ability_color_clear","value":value}],
                "animation_steps":[],
                "extra_turn":False,
                "board_regenerated":False,
            }

        return self._resolve_after_initial_clear(
            matched,
            [{"kind":"ability_color_clear","value":value}],
            record_steps=record_steps,
        )
