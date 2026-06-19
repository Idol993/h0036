import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from enum import Enum as PyEnum
from typing import Optional, List, Dict, Any

import aiomqtt
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Enum, Text, create_engine, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

try:
    import redis.asyncio as redis
except ImportError:
    redis = None

from billing import BillingEngine

Base = declarative_base()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./charging.db")
SYNC_DB_URL = os.getenv("SYNC_DATABASE_URL", "sqlite:///./charging.db")
MQTT_BROKER = os.getenv("MQTT_BROKER", "test.mosquitto.org")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

async_engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
sync_engine = create_engine(SYNC_DB_URL, echo=False)
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


class UserRole(str, PyEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    ADMIN = "admin"


class PileStatus(str, PyEnum):
    IDLE = "idle"
    CHARGING = "charging"
    FAULT = "fault"
    OFFLINE = "offline"


class PileType(str, PyEnum):
    FAST = "fast"
    SLOW = "slow"


class PaymentStatus(str, PyEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), default="")
    role = Column(Enum(UserRole), default=UserRole.OWNER)
    created_at = Column(DateTime, default=datetime.utcnow)


class Station(Base):
    __tablename__ = "stations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    address = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    pile_count = Column(Integer, default=0)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    piles = relationship("Pile", back_populates="station", cascade="all, delete-orphan")


class Pile(Base):
    __tablename__ = "piles"
    id = Column(Integer, primary_key=True, index=True)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    pile_code = Column(String(50), unique=True, index=True, nullable=False)
    pile_type = Column(Enum(PileType), default=PileType.SLOW)
    power = Column(Float, default=7.0)
    status = Column(Enum(PileStatus), default=PileStatus.OFFLINE)
    fault_code = Column(String(50), default="")
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    station = relationship("Station", back_populates="piles")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, index=True)
    user_phone = Column(String(20), index=True, nullable=False)
    pile_id = Column(Integer, ForeignKey("piles.id"), nullable=False)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    energy_kwh = Column(Float, default=0.0)
    energy_fee = Column(Float, default=0.0)
    service_fee = Column(Float, default=0.0)
    total_fee = Column(Float, default=0.0)
    payment_status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class BillingRule(Base):
    __tablename__ = "billing_rules"
    id = Column(Integer, primary_key=True, index=True)
    period_name = Column(String(50), nullable=False)
    start_hour = Column(Integer, nullable=False)
    end_hour = Column(Integer, nullable=False)
    price_per_kwh = Column(Float, nullable=False)
    is_active = Column(Boolean, default=True)


class PileStatusCache:
    def __init__(self):
        self._data: Dict[str, Dict] = {}
        self._redis = None

    async def init_redis(self):
        if redis is not None:
            try:
                self._redis = redis.from_url(REDIS_URL, decode_responses=True)
                await self._redis.ping()
            except Exception:
                self._redis = None

    async def set(self, pile_code: str, status: Dict):
        status["updated_at"] = time.time()
        self._data[pile_code] = status
        if self._redis:
            try:
                await self._redis.setex(f"pile:{pile_code}", 3600, json.dumps(status))
            except Exception:
                pass

    async def get(self, pile_code: str) -> Optional[Dict]:
        if self._redis:
            try:
                data = await self._redis.get(f"pile:{pile_code}")
                if data:
                    return json.loads(data)
            except Exception:
                pass
        return self._data.get(pile_code)

    async def get_all(self) -> Dict[str, Dict]:
        return self._data.copy()


status_cache = PileStatusCache()
billing_engine = BillingEngine()

pending_commands: Dict[str, asyncio.Event] = {}
command_results: Dict[str, Dict] = {}
ws_clients: List[WebSocket] = []


async def get_db():
    async with async_session() as session:
        yield session


def get_sync_db():
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


class StationCreate(BaseModel):
    name: str
    address: str
    latitude: float
    longitude: float
    pile_count: int = 0


class PileCreate(BaseModel):
    station_id: int
    pile_code: str
    pile_type: PileType = PileType.SLOW
    power: float = 7.0


class PileStatusUpdate(BaseModel):
    pile_code: str
    status: PileStatus
    fault_code: str = ""
    power_kw: float = 0.0


class StartChargingRequest(BaseModel):
    phone: str
    pile_code: str


class StopChargingRequest(BaseModel):
    order_no: str


class PileCommandRequest(BaseModel):
    pile_code: str
    command: str


class BillingRuleCreate(BaseModel):
    period_name: str
    start_hour: int
    end_hour: int
    price_per_kwh: float


class LoginRequest(BaseModel):
    phone: str
    password: str = ""


app = FastAPI(title="充电桩实时监控与扫码启停平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await status_cache.init_redis()
    db = SyncSessionLocal()
    try:
        existing_rules = db.query(BillingRule).count()
        if existing_rules == 0:
            default_rules = [
                BillingRule(period_name="峰时", start_hour=10, end_hour=15, price_per_kwh=1.5),
                BillingRule(period_name="峰时", start_hour=18, end_hour=21, price_per_kwh=1.5),
                BillingRule(period_name="谷时", start_hour=23, end_hour=7, price_per_kwh=0.4),
            ]
            db.add_all(default_rules)
            db.commit()
        existing_users = db.query(User).count()
        if existing_users == 0:
            db.add_all([
                User(phone="13800000001", role=UserRole.ADMIN),
                User(phone="13800000002", role=UserRole.OPERATOR),
                User(phone="13800000003", role=UserRole.OWNER),
            ])
            if db.query(Station).count() == 0:
                stations = [
                    Station(name="朝阳公园充电站", address="北京市朝阳区朝阳公园南门",
                            latitude=39.937, longitude=116.475, pile_count=6),
                    Station(name="中关村科技园站", address="北京市海淀区中关村大街1号",
                            latitude=39.984, longitude=116.316, pile_count=8),
                    Station(name="国贸CBD站", address="北京市朝阳区建国门外大街1号",
                            latitude=39.909, longitude=116.461, pile_count=10),
                ]
                db.add_all(stations)
                db.flush()
                pile_codes = 1
                for s in stations:
                    for i in range(s.pile_count):
                        pile_codes += 1
                        ptype = PileType.FAST if i % 3 == 0 else PileType.SLOW
                        pstatus = PileStatus.IDLE if i % 4 != 0 else (
                            PileStatus.FAULT if i % 5 == 0 else PileStatus.CHARGING)
                        db.add(Pile(station_id=s.id, pile_code=f"P{pile_codes:04d}",
                                    pile_type=ptype, power=120.0 if ptype == PileType.FAST else 7.0,
                                    status=pstatus))
                db.commit()
    finally:
        db.close()
    asyncio.create_task(mqtt_subscribe_loop())
    asyncio.create_task(offline_monitor_loop())
    asyncio.create_task(payment_timeout_loop())


async def mqtt_subscribe_loop():
    while True:
        try:
            async with aiomqtt.Client(MQTT_BROKER, port=MQTT_PORT) as client:
                await client.subscribe("station/+/pile/+/status")
                await client.subscribe("pile/+/cmd/ack")
                await client.subscribe("pile/+/charging/report")
                print(f"[MQTT] Connected to {MQTT_BROKER}:{MQTT_PORT}")
                async for message in client.messages:
                    try:
                        topic = str(message.topic)
                        payload = json.loads(message.payload.decode())
                        asyncio.create_task(handle_mqtt_message(topic, payload))
                    except Exception as e:
                        print(f"[MQTT] Message error: {e}")
        except Exception as e:
            print(f"[MQTT] Connection error, reconnect in 5s: {e}")
            await asyncio.sleep(5)


async def handle_mqtt_message(topic: str, payload: Dict):
    parts = topic.split("/")
    if topic.startswith("station/") and "pile" in topic and topic.endswith("/status"):
        pile_code = parts[3]
        await update_pile_status(pile_code, payload)
    elif topic.startswith("pile/") and topic.endswith("/cmd/ack"):
        pile_code = parts[1]
        result = payload.get("result", "ok")
        if pile_code in pending_commands:
            command_results[pile_code] = {"result": result, "data": payload}
            pending_commands[pile_code].set()
    elif topic.startswith("pile/") and topic.endswith("/charging/report"):
        pile_code = parts[1]
        await handle_charging_report(pile_code, payload)


async def update_pile_status(pile_code: str, payload: Dict):
    async with async_session() as db:
        pile = await db.get(Pile, None)
        result = await db.execute(
            __import__("sqlalchemy").select(Pile).where(Pile.pile_code == pile_code)
        )
        pile = result.scalar_one_or_none()
        if pile:
            old_status = pile.status
            new_status = PileStatus(payload.get("status", pile.status.value))
            pile.status = new_status
            pile.fault_code = payload.get("fault_code", "")
            pile.last_heartbeat = datetime.utcnow()
            await db.commit()
            await status_cache.set(pile_code, {
                "id": pile.id,
                "station_id": pile.station_id,
                "status": pile.status.value,
                "pile_type": pile.pile_type.value,
                "power": pile.power,
                "fault_code": pile.fault_code,
                "last_heartbeat": pile.last_heartbeat.isoformat(),
            })
            await broadcast_ws({
                "type": "pile_status",
                "pile_code": pile_code,
                "station_id": pile.station_id,
                "status": new_status.value,
                "fault_code": pile.fault_code,
            })


async def handle_charging_report(pile_code: str, payload: Dict):
    async with async_session() as db:
        result = await db.execute(
            __import__("sqlalchemy").select(Order).where(
                Order.pile_id == __import__("sqlalchemy").select(Pile.id).where(Pile.pile_code == pile_code).scalar_subquery(),
                Order.payment_status == PaymentStatus.PENDING,
                Order.end_time.is_(None)
            ).order_by(Order.id.desc()).limit(1)
        )
        order = result.scalar_one_or_none()
        if order:
            order.energy_kwh = float(payload.get("energy_kwh", order.energy_kwh))
            now = datetime.utcnow()
            duration_hours = (now - (order.start_time or now)).total_seconds() / 3600
            order.energy_fee, order.service_fee, order.total_fee = billing_engine.calculate(
                order.start_time or now, now, order.energy_kwh
            )
            await db.commit()
            await broadcast_ws({
                "type": "charging_progress",
                "order_no": order.order_no,
                "energy_kwh": order.energy_kwh,
                "total_fee": round(order.total_fee, 2),
            })


async def broadcast_ws(data: Dict):
    message = json.dumps(data, ensure_ascii=False)
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)


async def offline_monitor_loop():
    while True:
        try:
            db = SyncSessionLocal()
            try:
                threshold = datetime.utcnow() - timedelta(minutes=5)
                piles = db.query(Pile).filter(Pile.status != PileStatus.OFFLINE).all()
                for pile in piles:
                    if pile.last_heartbeat < threshold:
                        pile.status = PileStatus.OFFLINE
                        asyncio.create_task(status_cache.set(pile.pile_code, {
                            "id": pile.id, "station_id": pile.station_id,
                            "status": PileStatus.OFFLINE.value,
                            "pile_type": pile.pile_type.value,
                            "power": pile.power, "fault_code": "",
                            "last_heartbeat": pile.last_heartbeat.isoformat(),
                        }))
                        asyncio.create_task(broadcast_ws({
                            "type": "pile_status", "pile_code": pile.pile_code,
                            "station_id": pile.station_id,
                            "status": PileStatus.OFFLINE.value, "fault_code": "",
                        }))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[OfflineMonitor] Error: {e}")
        await asyncio.sleep(60)


async def payment_timeout_loop():
    while True:
        try:
            db = SyncSessionLocal()
            try:
                threshold = datetime.utcnow() - timedelta(minutes=15)
                pending = db.query(Order).filter(
                    Order.payment_status == PaymentStatus.PENDING,
                    Order.end_time.isnot(None),
                    Order.paid_at.is_(None),
                    Order.end_time < threshold
                ).all()
                for order in pending:
                    order.payment_status = PaymentStatus.CANCELLED
                    pile = db.query(Pile).filter(Pile.id == order.pile_id).first()
                    if pile and pile.status == PileStatus.CHARGING:
                        pile.status = PileStatus.IDLE
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"[PaymentTimeout] Error: {e}")
        await asyncio.sleep(60)


async def send_pile_command(pile_code: str, command: str, **kwargs) -> Dict:
    import json as _json
    event = asyncio.Event()
    pending_commands[pile_code] = event
    try:
        async with aiomqtt.Client(MQTT_BROKER, port=MQTT_PORT) as client:
            await client.publish(
                f"cmd/{pile_code}",
                payload=_json.dumps({"command": command, **kwargs}),
                qos=1
            )
        try:
            await asyncio.wait_for(event.wait(), timeout=10)
            return command_results.pop(pile_code, {"result": "ok"})
        except asyncio.TimeoutError:
            return {"result": "timeout"}
    finally:
        pending_commands.pop(pile_code, None)
        command_results.pop(pile_code, None)


@app.post("/api/auth/login")
def login(req: LoginRequest):
    db = next(get_sync_db())
    user = db.query(User).filter(User.phone == req.phone).first()
    if not user:
        user = User(phone=req.phone, role=UserRole.OWNER)
        db.add(user)
        db.commit()
        db.refresh(user)
    return {"success": True, "data": {"id": user.id, "phone": user.phone, "role": user.role.value}}


@app.get("/api/stations")
async def list_stations(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(Station).order_by(Station.id))
    stations = result.scalars().all()
    data = []
    for s in stations:
        piles_r = await db.execute(select(Pile).where(Pile.station_id == s.id))
        piles = piles_r.scalars().all()
        available = sum(1 for p in piles if p.status == PileStatus.IDLE)
        fault = sum(1 for p in piles if p.status == PileStatus.FAULT)
        data.append({
            "id": s.id, "name": s.name, "address": s.address,
            "latitude": s.latitude, "longitude": s.longitude,
            "pile_count": len(piles), "available": available, "fault": fault,
            "piles": [{
                "id": p.id, "pile_code": p.pile_code,
                "type": p.pile_type.value, "power": p.power,
                "status": p.status.value, "fault_code": p.fault_code,
            } for p in piles]
        })
    return {"success": True, "data": data}


@app.get("/api/stations/{station_id}")
async def get_station(station_id: int, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    station = await db.get(Station, station_id)
    if not station:
        raise HTTPException(404, "站点不存在")
    result = await db.execute(select(Pile).where(Pile.station_id == station_id))
    piles = result.scalars().all()
    return {"success": True, "data": {
        "id": station.id, "name": station.name, "address": station.address,
        "latitude": station.latitude, "longitude": station.longitude,
        "piles": [{
            "id": p.id, "pile_code": p.pile_code,
            "type": p.pile_type.value, "power": p.power,
            "status": p.status.value, "fault_code": p.fault_code,
        } for p in piles]
    }}


@app.get("/api/piles/{pile_code}")
async def get_pile(pile_code: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(Pile).where(Pile.pile_code == pile_code))
    pile = result.scalar_one_or_none()
    if not pile:
        raise HTTPException(404, "充电桩不存在")
    cached = await status_cache.get(pile_code)
    return {"success": True, "data": {
        "id": pile.id, "pile_code": pile.pile_code,
        "station_id": pile.station_id,
        "type": pile.pile_type.value, "power": pile.power,
        "status": (cached or {}).get("status", pile.status.value),
        "fault_code": (cached or {}).get("fault_code", pile.fault_code),
    }}


@app.post("/api/charging/start")
async def start_charging(req: StartChargingRequest, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(Pile).where(Pile.pile_code == req.pile_code))
    pile = result.scalar_one_or_none()
    if not pile:
        raise HTTPException(404, "充电桩不存在")
    if pile.status == PileStatus.CHARGING:
        raise HTTPException(400, "该充电桩正在使用中")
    if pile.status == PileStatus.FAULT:
        raise HTTPException(400, "该充电桩故障，无法使用")
    if pile.status == PileStatus.OFFLINE:
        raise HTTPException(400, "该充电桩离线，无法使用")
    cmd_result = await send_pile_command(req.pile_code, "start", phone=req.phone)
    if cmd_result.get("result") not in ("ok", "success"):
        raise HTTPException(500, f"启动失败: {cmd_result}")
    pile.status = PileStatus.CHARGING
    order_no = f"OD{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{pile.id:04d}"
    order = Order(
        order_no=order_no, user_phone=req.phone,
        pile_id=pile.id, start_time=datetime.utcnow(),
        payment_status=PaymentStatus.PENDING,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    await status_cache.set(req.pile_code, {
        "id": pile.id, "station_id": pile.station_id,
        "status": PileStatus.CHARGING.value,
        "pile_type": pile.pile_type.value, "power": pile.power,
        "fault_code": "", "last_heartbeat": datetime.utcnow().isoformat(),
    })
    await broadcast_ws({
        "type": "pile_status", "pile_code": req.pile_code,
        "station_id": pile.station_id,
        "status": PileStatus.CHARGING.value, "fault_code": "",
    })
    return {"success": True, "data": {"order_no": order_no, "start_time": order.start_time.isoformat()}}


@app.post("/api/charging/stop")
async def stop_charging(req: StopChargingRequest, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(Order).where(Order.order_no == req.order_no))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.end_time:
        return {"success": True, "data": {"order_no": order.order_no, "total_fee": round(order.total_fee, 2)}}
    pile = await db.get(Pile, order.pile_id)
    if pile:
        await send_pile_command(pile.pile_code, "stop")
    end_time = datetime.utcnow()
    energy = order.energy_kwh or max(0.5, (pile.power if pile else 7.0) * 0.2)
    energy_fee, service_fee, total_fee = billing_engine.calculate(order.start_time or end_time, end_time, energy)
    order.end_time = end_time
    order.energy_kwh = energy
    order.energy_fee = energy_fee
    order.service_fee = service_fee
    order.total_fee = total_fee
    if pile:
        pile.status = PileStatus.IDLE
    await db.commit()
    if pile:
        await status_cache.set(pile.pile_code, {
            "id": pile.id, "station_id": pile.station_id,
            "status": PileStatus.IDLE.value,
            "pile_type": pile.pile_type.value, "power": pile.power,
            "fault_code": "", "last_heartbeat": datetime.utcnow().isoformat(),
        })
        await broadcast_ws({
            "type": "pile_status", "pile_code": pile.pile_code,
            "station_id": pile.station_id,
            "status": PileStatus.IDLE.value, "fault_code": "",
        })
    return {"success": True, "data": {
        "order_no": order.order_no,
        "energy_kwh": round(energy, 2),
        "energy_fee": round(energy_fee, 2),
        "service_fee": round(service_fee, 2),
        "total_fee": round(total_fee, 2),
        "start_time": order.start_time.isoformat() if order.start_time else None,
        "end_time": end_time.isoformat(),
    }}


@app.get("/api/orders/current")
async def get_current_order(phone: str, pile_code: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, and_
    query = select(Order).where(
        Order.user_phone == phone, Order.end_time.is_(None)
    ).order_by(Order.id.desc()).limit(1)
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    if not order:
        return {"success": True, "data": None}
    pile = await db.get(Pile, order.pile_id)
    duration = int((datetime.utcnow() - (order.start_time or datetime.utcnow())).total_seconds())
    energy_fee, service_fee, total_fee = billing_engine.calculate(
        order.start_time or datetime.utcnow(), datetime.utcnow(), order.energy_kwh
    )
    return {"success": True, "data": {
        "order_no": order.order_no,
        "pile_code": pile.pile_code if pile else "",
        "pile_power": pile.power if pile else 7.0,
        "start_time": order.start_time.isoformat() if order.start_time else None,
        "duration_seconds": duration,
        "energy_kwh": round(order.energy_kwh, 2),
        "energy_fee": round(energy_fee, 2),
        "service_fee": round(service_fee, 2),
        "total_fee": round(total_fee, 2),
    }}


@app.get("/api/orders")
async def list_orders(
    phone: Optional[str] = None,
    station_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy import select, and_
    query = select(Order).order_by(Order.id.desc()).limit(500)
    conditions = []
    if phone:
        conditions.append(Order.user_phone == phone)
    if start_date:
        conditions.append(Order.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        conditions.append(Order.created_at <= datetime.fromisoformat(end_date))
    if conditions:
        query = query.where(and_(*conditions))
    result = await db.execute(query)
    orders = result.scalars().all()
    pile_ids = [o.pile_id for o in orders]
    piles = {}
    if pile_ids:
        from sqlalchemy import select as _s
        pr = await db.execute(_s(Pile).where(Pile.id.in_(pile_ids)))
        for p in pr.scalars().all():
            piles[p.id] = p
    data = []
    for o in orders:
        p = piles.get(o.pile_id)
        data.append({
            "id": o.id, "order_no": o.order_no,
            "user_phone": o.user_phone,
            "pile_code": p.pile_code if p else "",
            "pile_type": p.pile_type.value if p else "",
            "start_time": o.start_time.isoformat() if o.start_time else None,
            "end_time": o.end_time.isoformat() if o.end_time else None,
            "energy_kwh": round(o.energy_kwh, 2),
            "total_fee": round(o.total_fee, 2),
            "payment_status": o.payment_status.value,
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        })
    return {"success": True, "data": data}


@app.post("/api/orders/{order_no}/pay")
async def pay_order(order_no: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.payment_status == PaymentStatus.PAID:
        return {"success": True, "data": {"order_no": order_no, "paid": True}}
    if order.payment_status == PaymentStatus.CANCELLED:
        raise HTTPException(400, "订单已取消")
    order.payment_status = PaymentStatus.PAID
    order.paid_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "data": {
        "order_no": order_no, "total_fee": round(order.total_fee, 2),
        "paid_at": order.paid_at.isoformat(),
    }}


@app.post("/api/piles/command")
async def pile_command(req: PileCommandRequest, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(Pile).where(Pile.pile_code == req.pile_code))
    pile = result.scalar_one_or_none()
    if not pile:
        raise HTTPException(404, "充电桩不存在")
    cmd_result = await send_pile_command(req.pile_code, req.command)
    if req.command == "reboot":
        pile.status = PileStatus.OFFLINE
        await db.commit()
        await status_cache.set(req.pile_code, {
            "id": pile.id, "station_id": pile.station_id,
            "status": PileStatus.OFFLINE.value,
            "pile_type": pile.pile_type.value, "power": pile.power,
            "fault_code": "", "last_heartbeat": datetime.utcnow().isoformat(),
        })
        await broadcast_ws({
            "type": "pile_status", "pile_code": req.pile_code,
            "station_id": pile.station_id,
            "status": PileStatus.OFFLINE.value, "fault_code": "",
        })
    return {"success": True, "data": cmd_result}


@app.get("/api/admin/dashboard")
def admin_dashboard(db: Session = Depends(get_sync_db)):
    total_piles = db.query(Pile).count()
    online = db.query(Pile).filter(Pile.status != PileStatus.OFFLINE).count()
    charging = db.query(Pile).filter(Pile.status == PileStatus.CHARGING).count()
    fault = db.query(Pile).filter(Pile.status == PileStatus.FAULT).count()
    online_rate = round(online / total_piles * 100, 2) if total_piles > 0 else 0
    fault_rate = round(fault / total_piles * 100, 2) if total_piles > 0 else 0
    utilization = round(charging / online * 100, 2) if online > 0 else 0

    stations = db.query(Station).all()
    station_stats = []
    for s in stations:
        piles = db.query(Pile).filter(Pile.station_id == s.id).all()
        sc = sum(1 for p in piles if p.status == PileStatus.CHARGING)
        station_stats.append({"id": s.id, "name": s.name, "utilization": round(sc / max(len(piles), 1) * 100, 2)})
    station_stats.sort(key=lambda x: x["utilization"], reverse=True)

    today = datetime.utcnow().date()
    hourly_data = []
    for h in range(24):
        start = datetime.combine(today, datetime.min.time()) + timedelta(hours=h)
        end = start + timedelta(hours=1)
        orders_hour = db.query(Order).filter(
            Order.start_time >= start, Order.start_time < end
        ).all()
        energy = sum(o.energy_kwh for o in orders_hour)
        revenue = sum(o.total_fee for o in orders_hour)
        hourly_data.append({"hour": h, "energy_kwh": round(energy, 2), "revenue": round(revenue, 2)})

    total_today_orders = db.query(Order).filter(func.date(Order.created_at) == today).count()
    total_today_energy = db.query(func.coalesce(func.sum(Order.energy_kwh), 0)).filter(
        func.date(Order.start_time) == today
    ).scalar() or 0
    total_today_revenue = db.query(func.coalesce(func.sum(Order.total_fee), 0)).filter(
        func.date(Order.paid_at) == today
    ).scalar() or 0

    return {"success": True, "data": {
        "total_piles": total_piles,
        "online_piles": online,
        "online_rate": online_rate,
        "fault_count": fault,
        "fault_rate": fault_rate,
        "charging_count": charging,
        "utilization": utilization,
        "top_utilization_stations": station_stats[:10],
        "hourly_trend": hourly_data,
        "today_orders": total_today_orders,
        "today_energy": round(total_today_energy, 2),
        "today_revenue": round(total_today_revenue, 2),
    }}


@app.get("/api/billing/rules")
def list_billing_rules(db: Session = Depends(get_sync_db)):
    rules = db.query(BillingRule).filter(BillingRule.is_active == True).all()
    return {"success": True, "data": [
        {"id": r.id, "period_name": r.period_name,
         "start_hour": r.start_hour, "end_hour": r.end_hour,
         "price_per_kwh": r.price_per_kwh} for r in rules
    ]}


@app.post("/api/billing/rules")
def create_billing_rule(rule: BillingRuleCreate, db: Session = Depends(get_sync_db)):
    new_rule = BillingRule(**rule.model_dump(), is_active=True)
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return {"success": True, "data": {"id": new_rule.id}}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        all_piles = await status_cache.get_all()
        await websocket.send_text(json.dumps({"type": "init", "piles": all_piles}, ensure_ascii=False))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)
    except Exception:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
