import asyncio
import json
import os
import random
import string

import websockets

from room import Room


class Match3Server:
    def __init__(self):
        self.host = "0.0.0.0"
        self.port = int(
            os.environ.get(
                "PORT",
                "8765",
            )
        )

        self.rooms = {}
        # Monotonically increasing public-room display name counter.
        # Room codes still exist internally for joining/routing, but public
        # players see Room 1, Room 2, Room 3, ...
        self.next_public_room_number = 1

    @staticmethod
    def random_code():
        alphabet = (
            string.ascii_uppercase
            + string.digits
        )

        return "".join(
            random.choice(alphabet)
            for _ in range(4)
        )

    def create_room(self, public=False):
        code = self.random_code()

        while code in self.rooms:
            code = self.random_code()

        display_name = None
        if public:
            display_name = f"Room {self.next_public_room_number}"
            self.next_public_room_number += 1

        room = Room(
            code=code,
            public=public,
            display_name=display_name,
        )

        self.rooms[code] = room
        return room

    async def send_error(self, socket, message, code=None):
        payload = {
            "type": "error",
            "message": message,
        }

        if code:
            payload["code"] = code

        await socket.send(
            json.dumps(payload)
        )

    async def send_room_list(self, socket):
        rooms = [
            room.public_info()
            for room in self.rooms.values()
            if (
                room.public
                and not room.is_full
                and room.winner is None
            )
        ]

        rooms.sort(
            key=lambda item: item["code"]
        )

        await socket.send(
            json.dumps({
                "type": "room_list",
                "rooms": rooms,
            })
        )

    async def leave_current_room(
        self,
        socket,
        room,
        notify=True,
    ):
        if room is None:
            return

        removed_player = room.remove_socket(socket)

        if removed_player is None:
            return

        if room.is_empty:
            self.rooms.pop(
                room.code,
                None,
            )
            return

        if notify:
            await room.reset_after_player_left()

    async def join_room(
        self,
        socket,
        room,
    ):
        player = room.add_socket(socket)

        if player is None:
            return None

        await socket.send(
            json.dumps({
                "type": "joined",
                "room": room.code,
                "player": player,
                "public": room.public,
                "room_name": room.display_name or room.code,
                "rules_version": 29,
            })
        )

        await room.broadcast({
            "event": "player_joined",
        })

        return player

    async def handler(self, socket):
        room = None
        player = None

        try:
            async for raw in socket:
                try:
                    data = json.loads(raw)
                except Exception:
                    await self.send_error(
                        socket,
                        "Invalid JSON message",
                        "invalid_json",
                    )
                    continue

                action = data.get("action")

                if action == "list_rooms":
                    await self.send_room_list(socket)

                elif action == "state":
                    if room is None:
                        await self.send_error(
                            socket,
                            "You are not in a room",
                            "not_in_room",
                        )
                    else:
                        await room.send_state_to(socket)

                elif action == "leave":
                    await self.leave_current_room(
                        socket,
                        room,
                    )

                    room = None
                    player = None

                    await socket.send(
                        json.dumps({
                            "type": "left",
                        })
                    )

                elif action == "create":
                    if room is not None:
                        await self.leave_current_room(
                            socket,
                            room,
                        )

                    room = self.create_room(
                        public=bool(
                            data.get(
                                "public",
                                False,
                            )
                        )
                    )

                    player = await self.join_room(
                        socket,
                        room,
                    )

                elif action == "join":
                    code = str(
                        data.get(
                            "room",
                            "",
                        )
                    ).upper().strip()

                    if not code:
                        await self.send_error(
                            socket,
                            "Room code is required",
                            "missing_room_code",
                        )
                        continue

                    target = self.rooms.get(code)

                    if target is None:
                        await self.send_error(
                            socket,
                            "Room not found",
                            "room_not_found",
                        )
                        continue

                    if target.is_full:
                        await self.send_error(
                            socket,
                            "Room is full",
                            "room_full",
                        )
                        continue

                    if room is not None:
                        await self.leave_current_room(
                            socket,
                            room,
                        )

                    room = target

                    player = await self.join_room(
                        socket,
                        room,
                    )

                elif action == "new_game":
                    if room is None or player is None:
                        await self.send_error(
                            socket,
                            "You are not in a room",
                            "not_in_room",
                        )
                        continue

                    restart_result = await room.toggle_new_game_ready(
                        player,
                    )

                    if not restart_result["ok"]:
                        reason = restart_result["reason"]
                        await self.send_error(
                            socket,
                            reason.replace("_", " ").title(),
                            reason,
                        )

                elif action == "swap":
                    if room is None or player is None:
                        await self.send_error(
                            socket,
                            "You are not in a room",
                            "not_in_room",
                        )
                        continue

                    a = data.get("a")
                    b = data.get("b")

                    if (
                        not isinstance(a, list)
                        or len(a) != 2
                        or not isinstance(b, list)
                        or len(b) != 2
                    ):
                        await self.send_error(
                            socket,
                            "Invalid move format",
                            "invalid_move_format",
                        )
                        continue

                    try:
                        a = (
                            int(a[0]),
                            int(a[1]),
                        )
                        b = (
                            int(b[0]),
                            int(b[1]),
                        )
                    except Exception:
                        await self.send_error(
                            socket,
                            "Invalid coordinates",
                            "invalid_coordinates",
                        )
                        continue

                    move_result = await room.make_move(
                        player,
                        a,
                        b,
                    )

                    if not move_result["ok"]:
                        reason = move_result["reason"]

                        # no_match is already broadcast as an invalid move.
                        if reason != "no_match":
                            await self.send_error(
                                socket,
                                reason.replace("_", " ").title(),
                                reason,
                            )

                else:
                    await self.send_error(
                        socket,
                        "Unknown action",
                        "unknown_action",
                    )

        except websockets.exceptions.ConnectionClosed:
            pass

        finally:
            await self.leave_current_room(
                socket,
                room,
            )

    async def run(self):
        print(
            f"Match-3 server running on "
            f"{self.host}:{self.port}"
        )

        async with websockets.serve(
            self.handler,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=20,
        ):
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(
        Match3Server().run()
    )
