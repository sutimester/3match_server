import json

from board import ServerBoard

MAX_HP = 100


class Room:
    def __init__(self, code, public=False):
        self.code = code
        self.public = public
        self.sockets = []
        self.board = ServerBoard()
        self.hp = [MAX_HP, MAX_HP]
        self.color_scores = [[0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0]]
        self.turn = 0
        self.winner = None

    def public_info(self):
        return {
            "code": self.code,
            "players": len(self.sockets),
            "open": len(self.sockets) < 2,
        }

    def state_payload(self, extra=None):
        payload = {
            "type": "state",
            "room": self.code,
            "public": self.public,
            "board": self.board.grid,
            "hp": self.hp,
            "color_scores": self.color_scores,
            "turn": self.turn,
            "winner": self.winner,
            "players": len(self.sockets),
        }
        if extra:
            payload.update(extra)
        return payload

    async def broadcast(self, extra=None):
        payload = json.dumps(self.state_payload(extra))
        stale = []

        for socket in self.sockets:
            try:
                await socket.send(payload)
            except Exception:
                stale.append(socket)

        for socket in stale:
            if socket in self.sockets:
                self.sockets.remove(socket)

    async def make_move(self, player, a, b):
        if self.winner is not None or player != self.turn or len(self.sockets) < 2:
            return

        result = self.board.resolve_swap(a, b)
        if result is None:
            await self.broadcast({"event": "invalid", "invalid_player": player})
            return

        opponent = 1 - player
        # The player who initiated the move owns every consequence of
        # that move: all cascades, special clears, points and gray damage.
        # Only after this complete result is applied may the turn change.
        for color_index, points in enumerate(result["color_points"]):
            self.color_scores[player][color_index] += points
        self.hp[opponent] = max(0, self.hp[opponent] - result["damage"])

        if self.hp[opponent] <= 0:
            self.winner = player
        else:
            self.turn = opponent

        result["event"] = "move"
        result["mover"] = player
        await self.broadcast(result)
