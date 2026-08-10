import asyncio
import json

from board import ServerBoard

MAX_HP = 100


class Room:
    def __init__(self, code, public=False, display_name=None):
        self.code = code
        self.public = public
        self.display_name = display_name

        # Slots are stable: index 0 = player 1, index 1 = player 2.
        self.sockets = [None, None]

        self.board = ServerBoard()

        self.hp = [MAX_HP, MAX_HP]

        self.color_scores = [
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ]

        self.turn = 0
        self.winner = None
        self.move_number = 0
        self.restart_ready = [False, False]
        self.restart_pending = False

    @property
    def player_count(self):
        return sum(
            1
            for socket in self.sockets
            if socket is not None
        )

    @property
    def is_full(self):
        return self.player_count >= 2

    @property
    def is_empty(self):
        return self.player_count == 0

    def first_free_player(self):
        for player, socket in enumerate(self.sockets):
            if socket is None:
                return player
        return None

    def socket_for_player(self, player):
        if player not in (0, 1):
            return None
        return self.sockets[player]

    def player_for_socket(self, socket):
        for player, stored in enumerate(self.sockets):
            if stored is socket:
                return player
        return None

    def add_socket(self, socket):
        player = self.first_free_player()

        if player is None:
            return None

        self.sockets[player] = socket
        return player

    def remove_socket(self, socket):
        player = self.player_for_socket(socket)

        if player is not None:
            self.sockets[player] = None

        return player

    def public_info(self):
        return {
            # Code is retained in the protocol so clicking the public-room
            # entry can still join the correct server room.
            "code": self.code,
            "name": self.display_name or self.code,
            "players": self.player_count,
            "open": not self.is_full,
        }

    def state_payload(self, extra=None):
        payload = {
            "type": "state",
            "room": self.code,
            "public": self.public,
            "room_name": self.display_name or self.code,
            "board": self.board.grid,
            "hp": self.hp,
            "color_scores": self.color_scores,
            "turn": self.turn,
            "winner": self.winner,
            "players": self.player_count,
            "move_number": self.move_number,
            "restart_ready": self.restart_ready,
            "restart_pending": self.restart_pending,
            "rules_version": 33,
        }

        if extra:
            payload.update(extra)

        return payload

    async def send_state_to(self, socket, extra=None):
        await socket.send(
            json.dumps(
                self.state_payload(extra)
            )
        )

    async def broadcast(self, extra=None):
        raw = json.dumps(
            self.state_payload(extra)
        )

        dead = []

        for socket in self.sockets:
            if socket is None:
                continue

            try:
                await socket.send(raw)
            except Exception:
                dead.append(socket)

        for socket in dead:
            self.remove_socket(socket)

    async def make_move(self, player, a, b):
        # All online move authorization is server-side.
        if player not in (0, 1):
            return {
                "ok": False,
                "reason": "invalid_player",
            }

        if self.winner is not None:
            return {
                "ok": False,
                "reason": "game_over",
            }

        if self.player_count < 2:
            return {
                "ok": False,
                "reason": "waiting_for_opponent",
            }

        if player != self.turn:
            return {
                "ok": False,
                "reason": "not_your_turn",
            }

        if not self.board.in_bounds(a) or not self.board.in_bounds(b):
            return {
                "ok": False,
                "reason": "out_of_bounds",
            }

        if not self.board.adjacent(a, b):
            return {
                "ok": False,
                "reason": "not_adjacent",
            }

        result = self.board.resolve_swap(a, b)

        if result is None:
            await self.broadcast({
                "event": "invalid",
                "invalid_player": player,
                "reason": "no_match",
            })

            return {
                "ok": False,
                "reason": "no_match",
            }

        opponent = 1 - player

        # Entire consequence chain belongs to the player who made the move.
        for color_index, points in enumerate(
            result["color_points"]
        ):
            self.color_scores[player][color_index] += points

        self.hp[opponent] = max(
            0,
            self.hp[opponent] - result["damage"],
        )

        self.move_number += 1

        if self.hp[opponent] <= 0:
            self.winner = player

        elif result["extra_turn"]:
            # 4+ match anywhere in the chain.
            self.turn = player

        else:
            self.turn = opponent

        result.update({
            "event": "move",
            "mover": player,
            "next_turn": self.turn,
            "move_number": self.move_number,
        })

        await self.broadcast(result)

        return {
            "ok": True,
            "result": result,
        }

    async def _start_new_game_after_ready(self):
        """
        Both players are ready. Keep the green 2/2 state visible briefly,
        then create the fresh match. This runs in its own asyncio task so
        the websocket handler is never blocked.
        """
        await asyncio.sleep(0.65)

        # Room may have changed while waiting.
        if (
            self.player_count < 2
            or self.winner is None
            or not all(self.restart_ready)
        ):
            self.restart_pending = False
            return

        self.board = ServerBoard()
        self.hp = [MAX_HP, MAX_HP]
        self.color_scores = [
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ]
        self.turn = 0
        self.winner = None
        self.move_number = 0
        self.restart_ready = [False, False]
        self.restart_pending = False

        await self.broadcast({
            "event": "new_game",
        })

    async def set_new_game_ready(self, player):
        """
        One-way online rematch confirmation.

        A player pressing NEW GAME becomes ready and stays ready until:
        - the other player also becomes ready and the new game starts, or
        - someone leaves the room.

        Repeated clicks from the same player are harmless and do not toggle
        the ready state back off.
        """
        if player not in (0, 1):
            return {"ok": False, "reason": "invalid_player"}

        if self.player_count < 2:
            return {"ok": False, "reason": "waiting_for_opponent"}

        if self.winner is None:
            return {"ok": False, "reason": "game_not_over"}

        if self.restart_pending:
            return {"ok": True, "started": False, "already_pending": True}

        # Idempotent: clicking again cannot cancel readiness.
        self.restart_ready[player] = True

        ready_count = sum(1 for value in self.restart_ready if value)

        await self.broadcast({
            "event": "restart_ready",
            "ready_player": player,
            "ready_count": ready_count,
            "all_ready": ready_count == 2,
        })

        if ready_count == 2:
            self.restart_pending = True
            # Broadcast pending state immediately so both clients show green.
            await self.broadcast({
                "event": "restart_ready",
                "ready_player": player,
                "ready_count": 2,
                "all_ready": True,
            })

            asyncio.create_task(
                self._start_new_game_after_ready()
            )

            return {"ok": True, "started": False, "scheduled": True}

        return {"ok": True, "started": False}

    async def reset_after_player_left(self):
        """
        If one player leaves, the remaining player keeps the room,
        but the current match is reset so a new opponent cannot inherit
        HP/points/board state from the previous match.
        """
        if self.player_count != 1:
            return

        remaining_player = (
            0
            if self.sockets[0] is not None
            else 1
        )

        remaining_socket = self.sockets[remaining_player]

        # Move remaining player into Player 1 slot.
        self.sockets = [remaining_socket, None]

        self.board = ServerBoard()
        self.hp = [MAX_HP, MAX_HP]
        self.color_scores = [
            [0, 0, 0, 0, 0, 0],
            [0, 0, 0, 0, 0, 0],
        ]
        self.turn = 0
        self.winner = None
        self.move_number = 0
        self.restart_ready = [False, False]
        self.restart_pending = False

        await self.broadcast({
            "event": "player_left",
            "you_are_now": 0,
        })
