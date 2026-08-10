import random

ROWS = 8
COLS = 8
GRAY = 5
GRAY_DAMAGE = 10


class ServerBoard:
    def __init__(self):
        self.grid = self._create_board()

    def _creates_match(self, r, c):
        value = self.grid[r][c]
        return (
            c >= 2 and self.grid[r][c - 1] == value and self.grid[r][c - 2] == value
        ) or (
            r >= 2 and self.grid[r - 1][c] == value and self.grid[r - 2][c] == value
        )

    def _create_board(self):
        self.grid = [[0] * COLS for _ in range(ROWS)]
        for r in range(ROWS):
            for c in range(COLS):
                choices = list(range(6))
                random.shuffle(choices)
                for value in choices:
                    self.grid[r][c] = value
                    if not self._creates_match(r, c):
                        break
        return self.grid

    @staticmethod
    def adjacent(a, b):
        return abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1

    def swap(self, a, b):
        r1, c1 = a
        r2, c2 = b
        self.grid[r1][c1], self.grid[r2][c2] = self.grid[r2][c2], self.grid[r1][c1]

    def collect_runs(self):
        runs = []

        for r in range(ROWS):
            start = 0
            while start < COLS:
                value = self.grid[r][start]
                end = start + 1
                while end < COLS and self.grid[r][end] == value:
                    end += 1
                if value is not None and end - start >= 3:
                    runs.append({"dir": "h", "value": value, "cells": [(r, c) for c in range(start, end)]})
                start = end

        for c in range(COLS):
            start = 0
            while start < ROWS:
                value = self.grid[start][c]
                end = start + 1
                while end < ROWS and self.grid[end][c] == value:
                    end += 1
                if value is not None and end - start >= 3:
                    runs.append({"dir": "v", "value": value, "cells": [(r, c) for r in range(start, end)]})
                start = end

        return runs

    def expand_specials(self, runs):
        matched = set()
        specials = []

        for run in runs:
            cells = run["cells"]
            value = run["value"]
            matched.update(cells)

            if len(cells) >= 5:
                # Existing 5+ effect: clear every stone of the matched color.
                color_cells = {
                    (r, c)
                    for r in range(ROWS)
                    for c in range(COLS)
                    if self.grid[r][c] == value
                }
                matched.update(color_cells)

                # Also clear the complete column at the third matched cell.
                third_cell = cells[2]
                third_col = third_cell[1]
                matched.update((r, third_col) for r in range(ROWS))

                specials.append({"kind": "color_clear", "value": value})
                specials.append({
                    "kind": "five_column_clear",
                    "index": third_col,
                })
            elif len(cells) == 4:
                if run["dir"] == "h":
                    row = cells[0][0]
                    matched.update((row, c) for c in range(COLS))
                    specials.append({"kind": "row_clear", "index": row})
                else:
                    col = cells[0][1]
                    matched.update((r, col) for r in range(ROWS))
                    specials.append({"kind": "column_clear", "index": col})

        return matched, specials

    def collapse(self):
        for c in range(COLS):
            values = [self.grid[r][c] for r in range(ROWS) if self.grid[r][c] is not None]
            missing = ROWS - len(values)
            new_col = [random.randrange(6) for _ in range(missing)] + values
            for r in range(ROWS):
                self.grid[r][c] = new_col[r]

    def resolve_swap(self, a, b, record_steps=True):
        if not self.adjacent(a, b):
            return None

        self.swap(a, b)
        runs = self.collect_runs()

        if not runs:
            self.swap(a, b)
            return None

        total_gray = 0
        total_removed = 0
        cascade = 0
        specials = []
        color_points = [0, 0, 0, 0, 0, 0]
        animation_steps = []
        cascade_color_points = []
        extra_turn = False

        while runs:
            cascade += 1

            # Any 5+ match made during this move, including cascades,
            # grants another turn to the player who initiated the move.
            if any(len(run["cells"]) >= 5 for run in runs):
                extra_turn = True

            matched, new_specials = self.expand_specials(runs)
            specials.extend(new_specials)

            before_grid = [row[:] for row in self.grid] if record_steps else None

            # During the whole current turn/chain, EVERY removed non-gray
            # stone gives +1 point to its own color. Gray is the exception:
            # it gives no color points and instead damages the opponent by 10.
            step_color_points = [0, 0, 0, 0, 0, 0]

            for r, c in matched:
                value = self.grid[r][c]
                if value is None:
                    continue

                if value == GRAY:
                    total_gray += 1
                else:
                    color_points[value] += 1
                    step_color_points[value] += 1

            cascade_color_points.append(step_color_points)
            total_removed += len(matched)

            for r, c in matched:
                self.grid[r][c] = None

            self.collapse()

            if record_steps:
                animation_steps.append({
                    "before": before_grid,
                    "matched": [list(cell) for cell in sorted(matched)],
                    "after": [row[:] for row in self.grid],
                })

            runs = self.collect_runs()

        return {
            "damage": total_gray * GRAY_DAMAGE,
            "gray_removed": total_gray,
            "removed": total_removed,
            "cascade": cascade,
            "specials": specials,
            "color_points": color_points,
            "animation_steps": animation_steps,
            "cascade_color_points": cascade_color_points,
            "extra_turn": extra_turn,
        }
