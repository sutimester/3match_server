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
        self.port = int(os.environ.get("PORT", "8765"))
        self.rooms = {}

    @staticmethod
    def random_code():
        alphabet = string.ascii_uppercase + string.digits
        return "".join(random.choice(alphabet) for _ in range(4))

    def create_room(self, public=False):
        code = self.random_code()
        while code in self.rooms:
            code = self.random_code()

        room = Room(code, public)
        self.rooms[code] = room
        return room

    async def send_room_list(self, socket):
        public_rooms = [
            room.public_info()
            for room in self.rooms.values()
            if room.public and len(room.sockets) < 2 and room.winner is None
        ]
        public_rooms.sort(key=lambda room: room["code"])
        await socket.send(json.dumps({"type": "room_list", "rooms": public_rooms}))

    async def leave_room(self, socket, room, notify=True):
        if room is None:
            return

        if socket in room.sockets:
            room.sockets.remove(socket)

        if room.sockets:
            if notify:
                await room.broadcast({"event": "player_left"})
        else:
            self.rooms.pop(room.code, None)

    async def join_room(self, socket, room, player):
        if socket not in room.sockets:
            room.sockets.append(socket)

        await socket.send(json.dumps({
            "type": "joined",
            "room": room.code,
            "player": player,
            "public": room.public,
        }))
        await room.broadcast()

    async def handler(self, socket):
        room = None
        player = None

        try:
            async for raw in socket:
                try:
                    data = json.loads(raw)
                except Exception:
                    await socket.send(json.dumps({
                        "type": "error",
                        "message": "Invalid message",
                    }))
                    continue

                action = data.get("action")

                if action == "list_rooms":
                    await self.send_room_list(socket)

                elif action == "leave":
                    await self.leave_room(socket, room)
                    room = None
                    player = None
                    await socket.send(json.dumps({"type": "left"}))

                elif action == "create":
                    if room is not None:
                        await self.leave_room(socket, room)

                    room = self.create_room(bool(data.get("public", False)))
                    player = 0
                    await self.join_room(socket, room, player)

                elif action == "join":
                    code = str(data.get("room", "")).upper().strip()
                    target = self.rooms.get(code)

                    if target is None:
                        await socket.send(json.dumps({
                            "type": "error",
                            "message": "Room not found",
                        }))
                        continue

                    if target is room:
                        continue

                    if len(target.sockets) >= 2:
                        await socket.send(json.dumps({
                            "type": "error",
                            "message": "Room is full",
                        }))
                        continue

                    if room is not None:
                        await self.leave_room(socket, room)

                    room = target
                    player = 1
                    await self.join_room(socket, room, player)

                elif action == "swap":
                    if room is None or player is None:
                        await socket.send(json.dumps({
                            "type": "error",
                            "message": "You are not in a room",
                        }))
                        continue

                    a = data.get("a")
                    b = data.get("b")

                    if not (
                        isinstance(a, list) and len(a) == 2
                        and isinstance(b, list) and len(b) == 2
                    ):
                        await socket.send(json.dumps({
                            "type": "error",
                            "message": "Invalid move format",
                        }))
                        continue

                    await room.make_move(player, tuple(a), tuple(b))

                else:
                    await socket.send(json.dumps({
                        "type": "error",
                        "message": "Unknown action",
                    }))

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.leave_room(socket, room)


    async def run(self):
        print(f"Match-3 server running on {self.host}:{self.port}")
        async with websockets.serve(self.handler, self.host, self.port):
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(Match3Server().run())
