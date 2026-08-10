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

    async def handler(self, socket):
        room = None
        player = None

        try:
            async for raw in socket:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue

                action = data.get("action")

                if action == "list_rooms":
                    await self.send_room_list(socket)

                elif action == "create":
                    room = self.create_room(bool(data.get("public", False)))
                    room.sockets.append(socket)
                    player = 0

                    await socket.send(json.dumps({
                        "type": "joined",
                        "room": room.code,
                        "player": player,
                        "public": room.public,
                    }))
                    await room.broadcast()

                elif action == "join":
                    code = str(data.get("room", "")).upper().strip()
                    target = self.rooms.get(code)

                    if target is None:
                        await socket.send(json.dumps({"type": "error", "message": "Room not found"}))
                        continue

                    if len(target.sockets) >= 2:
                        await socket.send(json.dumps({"type": "error", "message": "Room is full"}))
                        continue

                    room = target
                    room.sockets.append(socket)
                    player = 1

                    await socket.send(json.dumps({
                        "type": "joined",
                        "room": room.code,
                        "player": player,
                        "public": room.public,
                    }))
                    await room.broadcast()

                elif action == "swap" and room is not None and player is not None:
                    a = data.get("a")
                    b = data.get("b")

                    if isinstance(a, list) and len(a) == 2 and isinstance(b, list) and len(b) == 2:
                        await room.make_move(player, tuple(a), tuple(b))

        except websockets.exceptions.ConnectionClosed:
            pass

        finally:
            if room is not None and socket in room.sockets:
                room.sockets.remove(socket)

                if room.sockets:
                    await room.broadcast({"event": "player_left"})
                else:
                    self.rooms.pop(room.code, None)

    async def run(self):
        print(f"Match-3 server running on {self.host}:{self.port}")
        async with websockets.serve(self.handler, self.host, self.port):
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(Match3Server().run())
