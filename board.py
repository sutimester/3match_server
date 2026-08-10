import random

ROWS = 8
COLS = 8
COLOR_COUNT = 6

RED = 0
GREEN = 1
BLUE = 2
YELLOW = 3
PURPLE = 4
GRAY = 5

GRAY_DAMAGE = 10


class ServerBoard:
    """
    Authoritative Match-3 board used by online multiplayer.

    The online client never decides:
    - whether a move is valid,
    - what disappears,
    - how many points are earned,
    - how much damage is dealt,
    - whether an extra turn is earned,
    - whether a dead board must be regenerated.
    """

    def __init__(self):
        self.grid = [[0] * COLS for _ in range(ROWS)]
        self.regenerate_playable()

    @staticmethod
    def in_bounds(cell):
        if not isinstance(cell, tuple) or len(cell) != 2:
            return False
        r, c = cell
        return (
            isinstance(r, int)
            and isinstance(c, int)
            and 0 <= r < ROWS
            and 0 <= c < COLS
        )

    @staticmethod
    def adjacent(a, b):
        return (
            ServerBoard.in_bounds(a)
            and ServerBoard.in_bounds(b)
            and abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
        )

    def clone(self):
        other = ServerBoard.__new__(ServerBoard)
        other.grid = [row[:] for row in self.grid]
        return other

    def load(self, grid):
        if (
            not isinstance(grid, list)
            or len(grid) != ROWS
            or any(not isinstance(row, list) or len(row) != COLS for row in grid)
        ):
            raise ValueError("Invalid board shape")

        self.grid = [row[:] for row in grid]

    def swap(self, a, b):
        r1, c1 = a
        r2, c2 = b
        self.grid[r1][c1], self.grid[r2][c2] = (
            self.grid[r2][c2],
            self.grid[r1][c1],
        )

    def _creates_start_match(self, r, c):
        value = self.grid[r][c]

        horizontal = (
            c >= 2
            and self.grid[r][c - 1] == value
            and self.grid[r][c - 2] == value
        )

        vertical = (
            r >= 2
            and self.grid[r - 1][c] == value
            and self.grid[r - 2][c] == value
        )

        return horizontal or vertical

    def _generate_without_matches(self):
        self.grid = [[0] * COLS for _ in range(ROWS)]

        for r in range(ROWS):
            for c in range(COLS):
                choices = list(range(COLOR_COUNT))
                random.shuffle(choices)

                for value in choices:
                    self.grid[r][c] = value
                    if not self._creates_start_match(r, c):
                        break

    def regenerate_playable(self):
        attempts = 0

        while True:
            attempts += 1
            self._generate_without_matches()

            if not self.collect_runs() and self.has_valid_move():
                return attempts

    def collect_runs(self):
        runs = []

        # Horizontal runs.
        for r in range(ROWS):
            start = 0

            while start < COLS:
                value = self.grid[r][start]
                end = start + 1

                while end < COLS and self.grid[r][end] == value:
                    end += 1

                if value is not None and end - start >= 3:
                    runs.append({
                        "dir": "h",
                        "value": value,
                        "cells": [(r, c) for c in range(start, end)],
                    })

                start = end

        # Vertical runs.
        for c in range(COLS):
            start = 0

            while start < ROWS:
                value = self.grid[start][c]
                end = start + 1

                while end < ROWS and self.grid[end][c] == value:
                    end += 1

                if value is not None and end - start >= 3:
                    runs.append({
                        "dir": "v",
                        "value": value,
                        "cells": [(r, c) for r in range(start, end)],
                    })

                start = end

        return runs

    def has_valid_move(self):
        for r in range(ROWS):
            for c in range(COLS):
                if c + 1 < COLS:
                    a = (r, c)
                    b = (r, c + 1)

                    self.swap(a, b)
                    valid = bool(self.collect_runs())
                    self.swap(a, b)

                    if valid:
                        return True

                if r + 1 < ROWS:
                    a = (r, c)
                    b = (r + 1, c)

                    self.swap(a, b)
                    valid = bool(self.collect_runs())
                    self.swap(a, b)

                    if valid:
                        return True

        return False

    def valid_moves(self):
        result = []

        for r in range(ROWS):
            for c in range(COLS):
                candidates = []

                if c + 1 < COLS:
                    candidates.append(((r, c), (r, c + 1)))

                if r + 1 < ROWS:
                    candidates.append(((r, c), (r + 1, c)))

                for a, b in candidates:
                    self.swap(a, b)
                    valid = bool(self.collect_runs())
                    self.swap(a, b)

                    if valid:
                        result.append((a, b))

        return result

    def _expand_specials(self, runs):
        matched = set()
        specials = []

        for run in runs:
            cells = run["cells"]
            value = run["value"]
            length = len(cells)

            # The actual matched stones always disappear.
            matched.update(cells)

            if length >= 6:
                # 6+ non-gray:
                # clear every stone of the matched color.
                #
                # 6+ gray:
                # gray is exempt from global color clear, so only the
                # actual matched gray run disappears.
                if value != GRAY:
                    color_cells = {
                        (r, c)
                        for r in range(ROWS)
                        for c in range(COLS)
                        if self.grid[r][c] == value
                    }

                    matched.update(color_cells)

                    specials.append({
                        "kind": "color_clear",
                        "value": value,
                        "length": length,
                    })
                else:
                    specials.append({
                        "kind": "gray_6plus_match",
                        "value": value,
                        "length": length,
                    })

            elif length == 5:
                # Exact 5:
                # clear full row + full column through the middle stone.
                middle_r, middle_c = cells[len(cells) // 2]

                matched.update(
                    (middle_r, c)
                    for c in range(COLS)
                )
                matched.update(
                    (r, middle_c)
                    for r in range(ROWS)
                )

                specials.append({
                    "kind": "cross_clear",
                    "row": middle_r,
                    "column": middle_c,
                })

            elif length == 4:
                # Exact 4:
                # horizontal -> entire row
                # vertical   -> entire column
                if run["dir"] == "h":
                    row = cells[0][0]

                    matched.update(
                        (row, c)
                        for c in range(COLS)
                    )

                    specials.append({
                        "kind": "row_clear",
                        "index": row,
                    })

                else:
                    col = cells[0][1]

                    matched.update(
                        (r, col)
                        for r in range(ROWS)
                    )

                    specials.append({
                        "kind": "column_clear",
                        "index": col,
                    })

        return matched, specials

    def _collapse(self):
        for c in range(COLS):
            survivors = [
                self.grid[r][c]
                for r in range(ROWS)
                if self.grid[r][c] is not None
            ]

            missing = ROWS - len(survivors)

            new_col = (
                [random.randrange(COLOR_COUNT) for _ in range(missing)]
                + survivors
            )

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

        color_points = [0] * COLOR_COUNT
        cascade_color_points = []

        cascade = 0
        specials = []
        animation_steps = []

        # 4+ anywhere in the entire consequence chain grants extra turn.
        extra_turn = False

        while runs:
            cascade += 1

            if any(len(run["cells"]) >= 4 for run in runs):
                extra_turn = True

            matched, step_specials = self._expand_specials(runs)
            specials.extend(step_specials)

            before = (
                [row[:] for row in self.grid]
                if record_steps
                else None
            )

            step_points = [0] * COLOR_COUNT

            # Every disappearing non-gray stone = +1 point for its color.
            # Every disappearing gray stone = 10 damage to opponent,
            # and gives no color point.
            for r, c in matched:
                value = self.grid[r][c]

                if value is None:
                    continue

                if value == GRAY:
                    total_gray += 1
                else:
                    color_points[value] += 1
                    step_points[value] += 1

            cascade_color_points.append(step_points)
            total_removed += len(matched)

            for r, c in matched:
                self.grid[r][c] = None

            self._collapse()

            if record_steps:
                animation_steps.append({
                    "before": before,
                    "matched": [
                        list(cell)
                        for cell in sorted(matched)
                    ],
                    "after": [
                        row[:]
                        for row in self.grid
                    ],
                    "color_points": step_points,
                    "gray_removed": sum(
                        1
                        for r, c in matched
                        if before[r][c] == GRAY
                    ),
                })

            runs = self.collect_runs()

        board_regenerated = False
        regenerate_attempts = 0

        # Dead-board rule.
        if not self.has_valid_move():
            regenerate_attempts = self.regenerate_playable()
            board_regenerated = True

        return {
            "color_points": color_points,
            "cascade_color_points": cascade_color_points,
            "gray_removed": total_gray,
            "damage": total_gray * GRAY_DAMAGE,
            "removed": total_removed,
            "cascade": cascade,
            "specials": specials,
            "animation_steps": animation_steps,
            "extra_turn": extra_turn,
            "board_regenerated": board_regenerated,
            "regenerate_attempts": regenerate_attempts,
        }
