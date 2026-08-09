import asyncio
import json
import random
import string
from dataclasses import dataclass, field

import websockets

HOST = "0.0.0.0"
PORT = int(__import__("os").environ.get("PORT", "8765"))

COLORS = [0, 1, 2, 3, 4, 5]  # 5 normal + gray
GRAY = 5
ROWS = 8
COLS = 8
MAX_HP = 100
GRAY_DAMAGE = 10


def random_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(4))


def creates_start_match(board, r, c):
    v = board[r][c]
    return (
        c >= 2 and board[r][c - 1] == v and board[r][c - 2] == v
    ) or (
        r >= 2 and board[r - 1][c] == v and board[r - 2][c] == v
    )


def make_board():
    board = [[0] * COLS for _ in range(ROWS)]
    for r in range(ROWS):
        for c in range(COLS):
            choices = COLORS[:]
            random.shuffle(choices)
            for v in choices:
                board[r][c] = v
                if not creates_start_match(board, r, c):
                    break
    return board


def collect_runs(board):
    runs = []

    for r in range(ROWS):
        start = 0
        while start < COLS:
            value = board[r][start]
            end = start + 1
            while end < COLS and board[r][end] == value:
                end += 1
            if value is not None and end - start >= 3:
                cells = [(r, c) for c in range(start, end)]
                runs.append({"dir": "h", "value": value, "cells": cells})
            start = end

    for c in range(COLS):
        start = 0
        while start < ROWS:
            value = board[start][c]
            end = start + 1
            while end < ROWS and board[end][c] == value:
                end += 1
            if value is not None and end - start >= 3:
                cells = [(r, c) for r in range(start, end)]
                runs.append({"dir": "v", "value": value, "cells": cells})
            start = end

    return runs


def expand_special_clears(board, runs):
    matched = set()
    special_events = []

    for run in runs:
        cells = run["cells"]
        value = run["value"]
        length = len(cells)
        matched.update(cells)

        if length >= 5:
            # 5+ match: clear every stone of that color.
            color_cells = {
                (r, c)
                for r in range(ROWS)
                for c in range(COLS)
                if board[r][c] == value
            }
            matched.update(color_cells)
            special_events.append({"kind": "color_clear", "value": value, "count": len(color_cells)})

        elif length == 4:
            # 4 match: horizontal clears row, vertical clears column.
            if run["dir"] == "h":
                r = cells[0][0]
                cleared = {(r, c) for c in range(COLS)}
                matched.update(cleared)
                special_events.append({"kind": "row_clear", "index": r})
            else:
                c = cells[0][1]
                cleared = {(r, c) for r in range(ROWS)}
                matched.update(cleared)
                special_events.append({"kind": "column_clear", "index": c})

    return matched, special_events


def collapse(board):
    for c in range(COLS):
        values = [board[r][c] for r in range(ROWS) if board[r][c] is not None]
        missing = ROWS - len(values)
        new_col = [random.choice(COLORS) for _ in range(missing)] + values
        for r in range(ROWS):
            board[r][c] = new_col[r]


def adjacent(a, b):
    r1, c1 = a
    r2, c2 = b
    return abs(r1 - r2) + abs(c1 - c2) == 1


@dataclass
class Room:
    code: str
    public: bool = False
    sockets: list = field(default_factory=list)
    board: list = field(default_factory=make_board)
    hp: list = field(default_factory=lambda: [MAX_HP, MAX_HP])
    score: list = field(default_factory=lambda: [0, 0])
    turn: int = 0
    winner: int | None = None

    def public_info(self):
        return {
            "code": self.code,
            "players": len(self.sockets),
            "open": len(self.sockets) < 2,
        }

    async def broadcast(self, extra=None):
        message = {
            "type": "state",
            "room": self.code,
            "public": self.public,
            "board": self.board,
            "hp": self.hp,
            "score": self.score,
            "turn": self.turn,
            "winner": self.winner,
            "players": len(self.sockets),
        }
        if extra:
            message.update(extra)

        stale = []
        for ws in self.sockets:
            try:
                await ws.send(json.dumps(message))
            except Exception:
                stale.append(ws)

        for ws in stale:
            if ws in self.sockets:
                self.sockets.remove(ws)

    async def do_swap(self, player, a, b):
        if self.winner is not None or player != self.turn or len(self.sockets) < 2:
            return

        if not adjacent(a, b):
            return

        r1, c1 = a
        r2, c2 = b
        if not (
            0 <= r1 < ROWS and 0 <= c1 < COLS
            and 0 <= r2 < ROWS and 0 <= c2 < COLS
        ):
            return

        self.board[r1][c1], self.board[r2][c2] = self.board[r2][c2], self.board[r1][c1]

        runs = collect_runs(self.board)
        if not runs:
            self.board[r1][c1], self.board[r2][c2] = self.board[r2][c2], self.board[r1][c1]
            await self.broadcast({"event": "invalid"})
            return

        total_gray = 0
        total_removed = 0
        cascade = 0
        special_events = []

        while runs:
            cascade += 1
            matched, specials = expand_special_clears(self.board, runs)
            special_events.extend(specials)

            total_gray += sum(1 for r, c in matched if self.board[r][c] == GRAY)
            total_removed += len(matched)

            for r, c in matched:
                self.board[r][c] = None

            collapse(self.board)
            runs = collect_runs(self.board)

        # Score rewards removal and cascades.
        gained_score = total_removed * 10 + max(0, cascade - 1) * 25
        gained_score += sum(
            50 if e["kind"] in ("row_clear", "column_clear") else 100
            for e in special_events
        )
        self.score[player] += gained_score

        opponent = 1 - player
        damage = total_gray * GRAY_DAMAGE
        self.hp[opponent] = max(0, self.hp[opponent] - damage)

        if self.hp[opponent] <= 0:
            self.winner = player
        else:
            self.turn = opponent

        await self.broadcast({
            "event": "move",
            "damage": damage,
            "gray_removed": total_gray,
            "removed": total_removed,
            "score_gain": gained_score,
            "cascade": cascade,
            "specials": special_events,
        })


rooms = {}


async def send_room_list(ws):
    public_rooms = [
        room.public_info()
        for room in rooms.values()
        if room.public and len(room.sockets) < 2 and room.winner is None
    ]
    public_rooms.sort(key=lambda item: item["code"])
    await ws.send(json.dumps({"type": "room_list", "rooms": public_rooms}))


async def handler(ws):
    room = None
    player = None

    try:
        async for raw in ws:
            try:
                data = json.loads(raw)
            except Exception:
                continue

            action = data.get("action")

            if action == "list_rooms":
                await send_room_list(ws)

            elif action == "create":
                code = random_code()
                while code in rooms:
                    code = random_code()

                room = Room(code=code, public=bool(data.get("public", False)))
                room.sockets.append(ws)
                rooms[code] = room
                player = 0

                await ws.send(json.dumps({
                    "type": "joined",
                    "room": code,
                    "player": player,
                    "public": room.public,
                }))
                await room.broadcast()

            elif action == "join":
                code = str(data.get("room", "")).upper().strip()
                target = rooms.get(code)

                if not target:
                    await ws.send(json.dumps({"type": "error", "message": "Room not found"}))
                    continue
                if len(target.sockets) >= 2:
                    await ws.send(json.dumps({"type": "error", "message": "Room is full"}))
                    continue

                room = target
                room.sockets.append(ws)
                player = 1

                await ws.send(json.dumps({
                    "type": "joined",
                    "room": code,
                    "player": player,
                    "public": room.public,
                }))
                await room.broadcast()

            elif action == "swap" and room is not None and player is not None:
                a = data.get("a")
                b = data.get("b")
                if isinstance(a, list) and len(a) == 2 and isinstance(b, list) and len(b) == 2:
                    await room.do_swap(player, tuple(a), tuple(b))

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        if room is not None and ws in room.sockets:
            room.sockets.remove(ws)
            if room.sockets:
                await room.broadcast({"event": "player_left"})
            else:
                rooms.pop(room.code, None)


async def main():
    print(f"Match-3 server running on {HOST}:{PORT}")
    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
