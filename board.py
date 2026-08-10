import random
ROWS=8
COLS=8
GRAY=5
GRAY_DAMAGE=10

COLOR_COUNT = 6


class ServerBoard:
    def __init__(self):
        self.grid = [[0] * COLS for _ in range(ROWS)]
        self.regenerate_playable()

    def clone(self):
        other = ServerBoard.__new__(ServerBoard)
        other.grid = [row[:] for row in self.grid]
        return other

    @staticmethod
    def in_bounds(cell):
        if not isinstance(cell, tuple) or len(cell) != 2:
            return False
        r, c = cell
        return isinstance(r, int) and isinstance(c, int) and 0 <= r < ROWS and 0 <= c < COLS

    @staticmethod
    def adjacent(a, b):
        return (
            ServerBoard.in_bounds(a)
            and ServerBoard.in_bounds(b)
            and abs(a[0]-b[0]) + abs(a[1]-b[1]) == 1
        )

    def load(self, grid):
        self.grid = [row[:] for row in grid]

    def swap(self, a, b):
        r1,c1 = a
        r2,c2 = b
        self.grid[r1][c1], self.grid[r2][c2] = self.grid[r2][c2], self.grid[r1][c1]

    def _creates_start_match(self, r, c):
        v = self.grid[r][c]
        return (
            c >= 2 and self.grid[r][c-1] == v and self.grid[r][c-2] == v
        ) or (
            r >= 2 and self.grid[r-1][c] == v and self.grid[r-2][c] == v
        )

    def _generate_without_matches(self):
        self.grid = [[0] * COLS for _ in range(ROWS)]
        for r in range(ROWS):
            for c in range(COLS):
                values = list(range(COLOR_COUNT))
                random.shuffle(values)
                for v in values:
                    self.grid[r][c] = v
                    if not self._creates_start_match(r,c):
                        break

    def regenerate_playable(self):
        while True:
            self._generate_without_matches()
            if not self.collect_runs() and self.has_valid_move():
                return

    def collect_runs(self):
        runs = []
        for r in range(ROWS):
            s = 0
            while s < COLS:
                v = self.grid[r][s]
                e = s + 1
                while e < COLS and self.grid[r][e] == v:
                    e += 1
                if v is not None and e-s >= 3:
                    runs.append({"dir":"h","value":v,"cells":[(r,c) for c in range(s,e)]})
                s = e

        for c in range(COLS):
            s = 0
            while s < ROWS:
                v = self.grid[s][c]
                e = s + 1
                while e < ROWS and self.grid[e][c] == v:
                    e += 1
                if v is not None and e-s >= 3:
                    runs.append({"dir":"v","value":v,"cells":[(r,c) for r in range(s,e)]})
                s = e
        return runs

    def has_valid_move(self):
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0] >= ROWS or b[1] >= COLS:
                        continue
                    a=(r,c)
                    self.swap(a,b)
                    ok = bool(self.collect_runs())
                    self.swap(a,b)
                    if ok:
                        return True
        return False

    def valid_moves(self):
        result=[]
        for r in range(ROWS):
            for c in range(COLS):
                for b in ((r,c+1),(r+1,c)):
                    if b[0] >= ROWS or b[1] >= COLS:
                        continue
                    a=(r,c)
                    self.swap(a,b)
                    ok=bool(self.collect_runs())
                    self.swap(a,b)
                    if ok:
                        clone=self.clone()
                        out=clone.resolve_swap(a,b,record_steps=False)
                        result.append((a,b,out))
        return result

    def _expand_specials(self, runs):
        matched=set()
        specials=[]
        for run in runs:
            cells=run["cells"]
            value=run["value"]
            n=len(cells)
            matched.update(cells)

            if n >= 6:
                if value != GRAY:
                    matched.update(
                        (r,c)
                        for r in range(ROWS)
                        for c in range(COLS)
                        if self.grid[r][c] == value
                    )
                    specials.append({"kind":"color_clear","value":value,"length":n})
                else:
                    specials.append({"kind":"gray_6plus_match","value":value,"length":n})

            elif n == 5:
                mr,mc=cells[len(cells)//2]
                matched.update((mr,c) for c in range(COLS))
                matched.update((r,mc) for r in range(ROWS))
                specials.append({"kind":"cross_clear","row":mr,"column":mc})

            elif n == 4:
                if run["dir"] == "h":
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
            survivors=[self.grid[r][c] for r in range(ROWS) if self.grid[r][c] is not None]
            missing=ROWS-len(survivors)
            col=[random.randrange(COLOR_COUNT) for _ in range(missing)] + survivors
            for r in range(ROWS):
                self.grid[r][c]=col[r]

    def resolve_swap(self,a,b,record_steps=True):
        if not self.adjacent(a,b):
            return None
        self.swap(a,b)
        runs=self.collect_runs()
        if not runs:
            self.swap(a,b)
            return None

        color_points=[0]*COLOR_COUNT
        cascade_points=[]
        total_gray=0
        total_removed=0
        cascade=0
        specials=[]
        steps=[]
        extra_turn=False

        while runs:
            cascade += 1
            if any(len(run["cells"]) >= 4 for run in runs):
                extra_turn=True

            matched,new_specials=self._expand_specials(runs)
            specials.extend(new_specials)
            before=[row[:] for row in self.grid] if record_steps else None
            step_points=[0]*COLOR_COUNT

            for r,c in matched:
                v=self.grid[r][c]
                if v is None:
                    continue
                if v == GRAY:
                    total_gray += 1
                else:
                    color_points[v] += 1
                    step_points[v] += 1

            cascade_points.append(step_points)
            total_removed += len(matched)

            for r,c in matched:
                self.grid[r][c]=None
            self._collapse()

            if record_steps:
                steps.append({
                    "before":before,
                    "matched":[list(x) for x in sorted(matched)],
                    "after":[row[:] for row in self.grid],
                    "color_points":step_points,
                })
            runs=self.collect_runs()

        regenerated=False
        if not self.has_valid_move():
            self.regenerate_playable()
            regenerated=True

        return {
            "color_points":color_points,
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
