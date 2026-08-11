import random
ROWS=8
COLS=8
GRAY=5
GRAY_DAMAGE=10

COLOR_COUNT=6

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
            c>=2 and self.grid[r][c-1]==v and self.grid[r][c-2]==v
        ) or (
            r>=2 and self.grid[r-1][c]==v and self.grid[r-2][c]==v
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
                v=self.grid[r][s];e=s+1
                while e<COLS and self.grid[r][e]==v:e+=1
                if v is not None and e-s>=3:
                    runs.append({"dir":"h","value":v,"cells":[(r,c) for c in range(s,e)]})
                s=e

        for c in range(COLS):
            s=0
            while s<ROWS:
                v=self.grid[s][c];e=s+1
                while e<ROWS and self.grid[e][c]==v:e+=1
                if v is not None and e-s>=3:
                    runs.append({"dir":"v","value":v,"cells":[(r,c) for r in range(s,e)]})
                s=e
        return runs

    def has_valid_move(self):
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0]>=ROWS or b[1]>=COLS:continue
                    a=(r,c)
                    self.swap(a,b)
                    ok=bool(self.collect_runs())
                    self.swap(a,b)
                    if ok:return True
        return False

    def valid_moves(self):
        out=[]
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0]>=ROWS or b[1]>=COLS:continue
                    a=(r,c)
                    self.swap(a,b)
                    ok=bool(self.collect_runs())
                    self.swap(a,b)
                    if ok:
                        sim=self.clone()
                        out.append((a,b,sim.resolve_swap(a,b,record_steps=False)))
        return out

    def _expand_specials(self,runs):
        matched=set()
        specials=[]

        for run in runs:
            cells=run["cells"]
            value=run["value"]
            n=len(cells)
            matched.update(cells)

            if n>=6:
                if value!=GRAY:
                    matched.update(
                        (r,c)
                        for r in range(ROWS)
                        for c in range(COLS)
                        if self.grid[r][c]==value
                    )
                    specials.append({"kind":"color_clear","value":value,"length":n})
                else:
                    specials.append({"kind":"gray_6plus_match","value":value,"length":n})

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
        The ONE scoring function used by normal matches, specials,
        cascades and the purple ability.

        Every removed non-gray stone = +1 point of that stone's color.
        Every removed gray stone = 10 damage and NO collectible point.
        A cell is scored at most once because callers pass a set.
        """
        points=[0]*COLOR_COUNT
        gray_removed=0
        removed=0

        for r,c in set(cells):
            v=self.grid[r][c]
            if v is None:
                continue
            removed+=1
            if v==GRAY:
                gray_removed+=1
            else:
                points[v]+=1

        return points,gray_removed,removed

    @staticmethod
    def _add_points(total,step):
        for i,v in enumerate(step):
            total[i]+=v

    def _clear_cells(self,matched,record_steps):
        before=[row[:] for row in self.grid] if record_steps else None
        step_points,gray_removed,removed=self._score_cells(matched)

        for r,c in matched:
            self.grid[r][c]=None

        self._collapse()

        step=None
        if record_steps:
            step={
                "before":before,
                "matched":[list(x) for x in sorted(matched)],
                "after":[row[:] for row in self.grid],
                "color_points":step_points[:],
                "gray_removed":gray_removed,
            }

        return step_points,gray_removed,removed,step

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
        total_removed=0
        specials=list(initial_specials or [])
        steps=[]
        cascade=0
        extra_turn=False

        p,g,n,step=self._clear_cells(initial_matched,record_steps)
        self._add_points(total_points,p)
        cascade_points.append(p)
        total_gray+=g
        total_removed+=n
        if step:steps.append(step)

        runs=self.collect_runs()
        while runs:
            cascade+=1

            if any(len(run["cells"])>=4 for run in runs):
                extra_turn=True

            matched,new_specials=self._expand_specials(runs)
            specials.extend(new_specials)

            p,g,n,step=self._clear_cells(matched,record_steps)
            self._add_points(total_points,p)
            cascade_points.append(p)
            total_gray+=g
            total_removed+=n
            if step:steps.append(step)

            runs=self.collect_runs()

        regenerated=False
        if not self.has_valid_move():
            self.regenerate_playable()
            regenerated=True

        return {
            "color_points":total_points,
            "cascade_color_points":cascade_points,
            "gray_removed":total_gray,
            "damage":total_gray*GRAY_DAMAGE,
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

        self.swap(a,b)
        runs=self.collect_runs()

        if not runs:
            self.swap(a,b)
            return None

        # The initial match may itself grant an extra turn.
        initial_extra=any(len(run["cells"])>=4 for run in runs)
        matched,specials=self._expand_specials(runs)

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
            if self.grid[r][c]==value
        }

        if not matched:
            return {
                "color_points":[0]*COLOR_COUNT,
                "cascade_color_points":[],
                "gray_removed":0,
                "damage":0,
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
