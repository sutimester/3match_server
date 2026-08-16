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

    def collect_runs(self):
        runs=[]
        for r in range(ROWS):
            s=0
            while s<COLS:
                raw=self.grid[r][s]
                v=base_color(raw)
                e=s+1
                while e<COLS and base_color(self.grid[r][e])==v:
                    e+=1
                if v is not None and e-s>=3:
                    runs.append({"dir":"h","value":v,"cells":[(r,c) for c in range(s,e)]})
                s=e

        for c in range(COLS):
            s=0
            while s<ROWS:
                raw=self.grid[s][c]
                v=base_color(raw)
                e=s+1
                while e<ROWS and base_color(self.grid[e][c])==v:
                    e+=1
                if v is not None and e-s>=3:
                    runs.append({"dir":"v","value":v,"cells":[(r,c) for r in range(s,e)]})
                s=e
        return runs

    def _direct_move_creates_match(self,a,b):
        if not self.adjacent(a,b):
            return False

        ar,ac=a
        br,bc=b
        raw_a=self.grid[ar][ac]
        raw_b=self.grid[br][bc]

        wildcard_target=None
        wildcard_after=None

        if raw_a==MULTICOLOR and base_color(raw_b) in range(5):
            wildcard_target=base_color(raw_b)
            wildcard_after=b
        elif raw_b==MULTICOLOR and base_color(raw_a) in range(5):
            wildcard_target=base_color(raw_a)
            wildcard_after=a

        self.swap(a,b)

        if wildcard_after is not None:
            wr,wc=wildcard_after
            self.grid[wr][wc]=wildcard_target

        runs=self.collect_runs()

        if wildcard_after is not None:
            ok=any(wildcard_after in run["cells"] for run in runs)
        else:
            ok=bool(runs)

        self.grid[ar][ac]=raw_a
        self.grid[br][bc]=raw_b
        return ok

    def has_valid_move(self):
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0]>=ROWS or b[1]>=COLS:
                        continue
                    if self._direct_move_creates_match((r,c),b):
                        return True
        return False

    def valid_moves(self):
        out=[]
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0]>=ROWS or b[1]>=COLS:
                        continue
                    a=(r,c)
                    if self._direct_move_creates_match(a,b):
                        sim=self.clone()
                        out.append((a,b,sim.resolve_swap(a,b,record_steps=False)))
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

    def _collapse(self):
        for c in range(COLS):
            survivors=[
                self.grid[r][c]
                for r in range(ROWS)
                if self.grid[r][c] is not None
            ]
            missing=ROWS-len(survivors)
            values=[random.randrange(COLOR_COUNT) for _ in range(missing)]+survivors
            for r in range(ROWS):
                self.grid[r][c]=values[r]

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

    def _clear_cells(self,matched,record_steps,specials=None):
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

        self._collapse()

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

        p,g,w,n,step,gv,wv=self._clear_cells(initial_matched,record_steps,initial_specials)
        self._add_points(total_points,p)
        cascade_points.append(p)
        total_gray+=g
        total_white+=w
        total_removed+=n
        total_gray_value+=gv
        total_white_value+=wv
        if step:steps.append(step)

        runs=self.collect_runs()
        while runs:
            cascade+=1

            if any(len(run["cells"])>=4 for run in runs):
                extra_turn=True

            matched,new_specials=self._expand_specials(runs)
            specials.extend(new_specials)

            p,g,w,n,step,gv,wv=self._clear_cells(matched,record_steps,new_specials)
            self._add_points(total_points,p)
            cascade_points.append(p)
            total_gray+=g
            total_white+=w
            total_removed+=n
            total_gray_value+=gv
            total_white_value+=wv
            if step:steps.append(step)

            runs=self.collect_runs()

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

    def resolve_swap(self,a,b,record_steps=True):
        if not self.adjacent(a,b):
            return None

        ar,ac=a
        br,bc=b
        raw_a=self.grid[ar][ac]
        raw_b=self.grid[br][bc]

        # Multicolor wildcard may only act during this direct player move.
        # It is deliberately invisible to collect_runs() during cascades.
        wildcard_move=False
        wildcard_target=None
        wildcard_cell_after=None

        if raw_a==MULTICOLOR and base_color(raw_b) in range(5):
            wildcard_move=True
            wildcard_target=base_color(raw_b)
            wildcard_cell_after=b
        elif raw_b==MULTICOLOR and base_color(raw_a) in range(5):
            wildcard_move=True
            wildcard_target=base_color(raw_a)
            wildcard_cell_after=a

        self.swap(a,b)

        if wildcard_move:
            wr,wc=wildcard_cell_after
            # For this one direct move only, treat the multicolor stone as the
            # chosen normal color. If the move fails it is restored below.
            self.grid[wr][wc]=wildcard_target

        runs=self.collect_runs()

        # A directly moved wildcard must itself participate in the new match.
        if wildcard_move:
            if not any(wildcard_cell_after in run["cells"] for run in runs):
                self.grid[ar][ac]=raw_a
                self.grid[br][bc]=raw_b
                return None

        if not runs:
            self.grid[ar][ac]=raw_a
            self.grid[br][bc]=raw_b
            return None

        # T5 is checked ONLY here, so cascades can never create the wildcard.
        t5=self._detect_t5(runs)

        if t5 is not None:
            matched=set(t5["cells"])
            intersection=t5["intersection"]
            specials=[{
                "kind":"multicolor_t5",
                "value":t5["value"],
                "cell":list(intersection),
            }]
            initial_extra=True
        else:
            initial_extra=any(len(run["cells"])>=4 for run in runs)
            preferred=None
            for candidate in (b,a):
                if any(candidate in run["cells"] for run in runs):
                    preferred=candidate
                    break

            matched,specials=self._expand_specials(
                runs,
                preferred_special_cell=preferred,
            )

        if wildcard_move:
            specials.append({
                "kind":"multicolor_used",
                "value":wildcard_target,
                "cell":list(wildcard_cell_after),
            })

        result=self._resolve_after_initial_clear(
            matched,
            specials,
            record_steps=record_steps,
            initial_counts_as_match=True,
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
