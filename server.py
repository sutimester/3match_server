import asyncio,json,os,random,string
import websockets
from room import Room

class Match3Server:
    def __init__(self):
        self.host="0.0.0.0"
        self.port=int(os.environ.get("PORT","8765"))
        self.rooms={}
        self.next_public_room_number=1

    def random_code(self):
        chars=string.ascii_uppercase+string.digits
        return "".join(random.choice(chars) for _ in range(4))

    def create_room(self,public=False):
        code=self.random_code()
        while code in self.rooms:code=self.random_code()
        name=None
        if public:
            name=f"Room {self.next_public_room_number}"
            self.next_public_room_number+=1
        room=Room(code,public,name);self.rooms[code]=room
        return room

    async def send_error(self,socket,msg,code=None):
        d={"type":"error","message":msg}
        if code:d["code"]=code
        await socket.send(json.dumps(d))

    async def send_room_list(self,socket):
        rooms=[
            r.public_info()
            for r in self.rooms.values()
            if r.public and r.winner is None
        ]
        await socket.send(json.dumps({"type":"room_list","rooms":rooms}))

    async def leave(self,socket,room):
        if not room:return
        removed=room.remove_socket(socket)
        if removed is None:return
        if room.is_empty:self.rooms.pop(room.code,None)
        else:await room.reset_after_leave()

    async def leave_spectator(self,socket,room):
        if room is None:
            return

        room.remove_spectator(socket)

        if room.is_empty:
            self.rooms.pop(room.code,None)

    async def join_spectator(self,socket,room):
        if not room.public:
            await self.send_error(
                socket,
                "Only public rooms can be watched",
                "spectator_public_only",
            )
            return False

        if not room.is_live:
            await self.send_error(
                socket,
                "Spectator mode is only available for live public matches",
                "match_not_live",
            )
            return False

        room.add_spectator(socket)

        await socket.send(json.dumps({
            "type":"spectating",
            "room":room.code,
            "room_name":room.display_name or room.code,
            "public":True,
            "rules_version":45,
        }))

        await socket.send(json.dumps(
            room.state_payload({
                "event":"spectator_joined",
                "spectator_mode":True,
            })
        ))

        return True

    async def join_room(self,socket,room):
        p=room.add_socket(socket)
        if p is None:return None
        await socket.send(json.dumps({
            "type":"joined","room":room.code,"room_name":room.display_name or room.code,
            "player":p,"public":room.public,"rules_version":45
        }))
        await room.broadcast({"event":"player_joined"})
        return p

    async def handler(self,socket):
        room=None
        player=None
        spectator=False
        try:
            async for raw in socket:
                try:data=json.loads(raw)
                except Exception:continue
                action=data.get("action")

                if action=="list_rooms":
                    await self.send_room_list(socket)

                elif action=="create":
                    if room:
                        if spectator:
                            await self.leave_spectator(socket,room)
                        else:
                            await self.leave(socket,room)

                    room=self.create_room(bool(data.get("public",False)))
                    player=await self.join_room(socket,room)
                    spectator=False

                elif action=="join":
                    code=str(data.get("room","")).upper().strip()
                    target=self.rooms.get(code)
                    if target is None:
                        await self.send_error(socket,"Room not found","room_not_found");continue
                    if target.is_full:
                        await self.send_error(socket,"Room is full","room_full");continue
                    if room:
                        if spectator:
                            await self.leave_spectator(socket,room)
                        else:
                            await self.leave(socket,room)

                    room=target
                    player=await self.join_room(socket,room)
                    spectator=False

                elif action=="watch":
                    code=str(data.get("room","")).upper().strip()
                    target=self.rooms.get(code)

                    if target is None:
                        await self.send_error(
                            socket,
                            "Room not found",
                            "room_not_found",
                        )
                        continue

                    if room:
                        if spectator:
                            await self.leave_spectator(socket,room)
                        else:
                            await self.leave(socket,room)

                    ok=await self.join_spectator(socket,target)

                    if ok:
                        room=target
                        player=None
                        spectator=True
                    else:
                        room=None
                        player=None
                        spectator=False

                elif action=="leave":
                    if spectator:
                        await self.leave_spectator(socket,room)
                    else:
                        await self.leave(socket,room)

                    room=None
                    player=None
                    spectator=False
                    await socket.send(json.dumps({"type":"left"}))

                elif action=="set_name":
                    if spectator:
                        await self.send_error(
                            socket,
                            "Spectators cannot change game state",
                            "spectator_read_only",
                        )
                        continue

                    if room is not None and player is not None:
                        await room.set_player_name(player,data.get("name",""))

                elif action=="ability":
                    if spectator:
                        await self.send_error(
                            socket,
                            "Spectators cannot use abilities",
                            "spectator_read_only",
                        )
                        continue
                    if room is None or player is None:continue
                    try:a=int(data.get("ability"))
                    except Exception:continue
                    out=await room.use_ability(
                        player,
                        a,
                        data.get("target_color"),
                    )
                    if not out["ok"]:await self.send_error(socket,out["reason"].replace("_"," ").title(),out["reason"])

                elif action=="new_game":
                    if spectator:
                        await self.send_error(
                            socket,
                            "Spectators cannot request a new game",
                            "spectator_read_only",
                        )
                        continue

                    if room is None or player is None:
                        continue
                    out=await room.set_restart_ready(player)
                    if not out["ok"]:await self.send_error(socket,out["reason"].replace("_"," ").title(),out["reason"])

                elif action=="swap":
                    if spectator:
                        await self.send_error(
                            socket,
                            "Spectators cannot make moves",
                            "spectator_read_only",
                        )
                        continue

                    if room is None or player is None:
                        continue
                    a=data.get("a");b=data.get("b")
                    if not (isinstance(a,list) and len(a)==2 and isinstance(b,list) and len(b)==2):continue
                    try:a=(int(a[0]),int(a[1]));b=(int(b[0]),int(b[1]))
                    except Exception:continue
                    out=await room.make_move(player,a,b)
                    if not out["ok"] and out["reason"]!="no_match":
                        await self.send_error(socket,out["reason"].replace("_"," ").title(),out["reason"])

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if spectator:
                await self.leave_spectator(socket,room)
            else:
                await self.leave(socket,room)

    async def run(self):
        print(f"Match-3 server on {self.host}:{self.port}")
        async with websockets.serve(self.handler,self.host,self.port,ping_interval=20,ping_timeout=20):
            await asyncio.Future()

if __name__=="__main__":
    asyncio.run(Match3Server().run())
