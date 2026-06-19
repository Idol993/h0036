import asyncio
import json
import os
import sys
import time
import secrets
import io
import csv
from datetime import datetime, timedelta, date
from enum import Enum as PyEnum
from typing import Optional, List, Dict, Any, Tuple

if sys.platform == 'win32':
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

import aiomqtt
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Enum, Text, create_engine, func, and_
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
sync_engine = create_engine(SYNC_DB_URL, echo=False, pool_pre_ping=True)
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
    ONLINE = "online"


class PileType(str, PyEnum):
    FAST = "fast"
    SLOW = "slow"


class PaymentStatus(str, PyEnum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"


class WorkOrderStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RESOLVED = "resolved"
    CLOSED = "closed"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), default="")
    role = Column(Enum(UserRole, values_callable=lambda x: [e.value for e in x]), default=UserRole.OWNER)
    token = Column(String(64), unique=True, index=True, default="")
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
    pile_type = Column(Enum(PileType, values_callable=lambda x: [e.value for e in x]), default=PileType.SLOW)
    power = Column(Float, default=7.0)
    status = Column(Enum(PileStatus, values_callable=lambda x: [e.value for e in x]), default=PileStatus.OFFLINE)
    fault_code = Column(String(50), default="")
    last_heartbeat = Column(DateTime, default=datetime.utcnow)
    station = relationship("Station", back_populates="piles")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, index=True)
    user_phone = Column(String(20), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    pile_id = Column(Integer, ForeignKey("piles.id"), nullable=False)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    energy_kwh = Column(Float, default=0.0)
    energy_fee = Column(Float, default=0.0)
    service_fee = Column(Float, default=0.0)
    total_fee = Column(Float, default=0.0)
    payment_status = Column(Enum(PaymentStatus, values_callable=lambda x: [e.value for e in x]), default=PaymentStatus.PENDING)
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


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id = Column(Integer, primary_key=True, index=True)
    order_no = Column(String(50), unique=True, index=True)
    pile_id = Column(Integer, ForeignKey("piles.id"), nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)
    fault_code = Column(String(100), default="")
    fault_description = Column(Text, default="")
    status = Column(Enum(WorkOrderStatus, values_callable=lambda x: [e.value for e in x]), default=WorkOrderStatus.PENDING)
    handler_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    handler_name = Column(String(50), default="")
    result = Column(Text, default="")
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
fault_pile_ids: set = set()


async def get_db():
    async with async_session() as session:
        yield session


def get_sync_db():
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_user_by_token_sync(token: str, db: Session) -> Optional[User]:
    if not token:
        return None
    return db.query(User).filter(User.token == token).first()


def get_current_user(authorization: Optional[str] = Header(None), x_token: Optional[str] = Header(None)) -> Optional[User]:
    db = next(get_sync_db())
    token = authorization.replace("Bearer ", "") if authorization else (x_token or "")
    return _get_user_by_token_sync(token, db)


def require_roles(*roles: UserRole):
    def dependency(user: Optional[User] = Depends(get_current_user)) -> User:
        if not user:
            raise HTTPException(401, "未登录或登录已过期")
        if user.role not in roles:
            raise HTTPException(403, "权限不足")
        return user
    return dependency


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


class CreateWorkOrderRequest(BaseModel):
    pile_code: str
    fault_code: str = ""
    fault_description: str = ""


class HandleWorkOrderRequest(BaseModel):
    result: str = ""
    status: WorkOrderStatus = WorkOrderStatus.RESOLVED


app = FastAPI(title="充电桩实时监控与扫码启停平台", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _generate_token() -> str:
    return secrets.token_hex(32)


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
            admin = User(phone="13800000001", role=UserRole.ADMIN, token=_generate_token())
            operator = User(phone="13800000002", role=UserRole.OPERATOR, token=_generate_token())
            owner = User(phone="13800000003", role=UserRole.OWNER, token=_generate_token())
            db.add_all([admin, operator, owner])
            db.flush()
            if db.query(Station).count() == 0:
                stations = [
                    Station(name="朝阳公园充电站", address="北京市朝阳区朝阳公园南门",
                            latitude=39.937, longitude=116.475, pile_count=6, operator_id=operator.id),
                    Station(name="中关村科技园站", address="北京市海淀区中关村大街1号",
                            latitude=39.984, longitude=116.316, pile_count=8, operator_id=operator.id),
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
    asyncio.create_task(_safe_mqtt_subscribe())
    asyncio.create_task(offline_monitor_loop())
    asyncio.create_task(payment_timeout_loop())


async def _safe_mqtt_subscribe():
    import asyncio as _asyncio
    try:
        await mqtt_subscribe_loop()
    except Exception as e:
        print(f"[MQTT] Fatal error, MQTT disabled: {e}")


async def mqtt_subscribe_loop():
    retry_count = 0
    max_retries = 10
    while retry_count < max_retries:
        try:
            async with aiomqtt.Client(MQTT_BROKER, port=MQTT_PORT) as client:
                await client.subscribe("station/+/pile/+/status")
                await client.subscribe("pile/+/cmd/ack")
                await client.subscribe("pile/+/charging/report")
                print(f"[MQTT] Connected to {MQTT_BROKER}:{MQTT_PORT}")
                retry_count = 0
                async for message in client.messages:
                    try:
                        topic = str(message.topic)
                        payload = json.loads(message.payload.decode())
                        asyncio.create_task(handle_mqtt_message(topic, payload))
                    except Exception as e:
                        print(f"[MQTT] Message error: {e}")
        except Exception as e:
            retry_count += 1
            print(f"[MQTT] Connection error (attempt {retry_count}/{max_retries}), reconnect in 5s: {e}")
            await asyncio.sleep(5)
    print("[MQTT] Max retries reached, MQTT subscription stopped")


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
    from sqlalchemy import select
    async with async_session() as db:
        result = await db.execute(select(Pile).where(Pile.pile_code == pile_code))
        pile = result.scalar_one_or_none()
        if pile:
            old_status = pile.status
            new_status = PileStatus(payload.get("status", pile.status.value))
            if old_status == PileStatus.FAULT:
                fault_pile_ids.add(pile.id)
            pile.status = new_status
            pile.fault_code = payload.get("fault_code", "")
            pile.last_heartbeat = datetime.utcnow()
            await db.commit()
            if new_status in (PileStatus.ONLINE, PileStatus.IDLE, PileStatus.CHARGING) and pile.id in fault_pile_ids:
                fault_pile_ids.discard(pile.id)
                wo_result = await db.execute(
                    select(WorkOrder).where(
                        WorkOrder.pile_id == pile.id,
                        WorkOrder.status.in_([WorkOrderStatus.PENDING, WorkOrderStatus.PROCESSING])
                    ).order_by(WorkOrder.id.desc())
                )
                pending_wos = wo_result.scalars().all()
                for wo in pending_wos:
                    wo.status = WorkOrderStatus.RESOLVED
                    wo.result = "设备恢复在线，自动关闭工单"
                    wo.resolved_at = datetime.utcnow()
                if pending_wos:
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
    from sqlalchemy import select
    async with async_session() as db:
        subq = select(Pile.id).where(Pile.pile_code == pile_code).scalar_subquery()
        result = await db.execute(
            select(Order).where(
                Order.pile_id == subq,
                Order.payment_status == PaymentStatus.PENDING,
                Order.end_time.is_(None)
            ).order_by(Order.id.desc()).limit(1)
        )
        order = result.scalar_one_or_none()
        if order:
            order.energy_kwh = float(payload.get("energy_kwh", order.energy_kwh))
            now = datetime.utcnow()
            e_fee, s_fee, t_fee = billing_engine.calculate(
                order.start_time or now, now, order.energy_kwh
            )
            order.energy_fee = e_fee
            order.service_fee = s_fee
            order.total_fee = t_fee
            await db.commit()
            await broadcast_ws({
                "type": "charging_progress",
                "order_no": order.order_no,
                "energy_kwh": round(order.energy_kwh, 2),
                "energy_fee": round(order.energy_fee, 2),
                "service_fee": round(order.service_fee, 2),
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


async def send_pile_command_fire_and_forget(pile_code: str, command: str, **kwargs):
    try:
        import json as _json
        async with aiomqtt.Client(MQTT_BROKER, port=MQTT_PORT) as client:
            await client.publish(
                f"cmd/{pile_code}",
                payload=_json.dumps({"command": command, **kwargs}),
                qos=1
            )
    except Exception as e:
        print(f"[MQTT-CMD] {pile_code} {command} failed: {e}")


@app.post("/api/auth/login")
def login(req: LoginRequest):
    db = next(get_sync_db())
    user = db.query(User).filter(User.phone == req.phone).first()
    if not user:
        user = User(phone=req.phone, role=UserRole.OWNER, token=_generate_token())
        db.add(user)
    else:
        if not user.token:
            user.token = _generate_token()
    db.commit()
    db.refresh(user)
    return {"success": True, "data": {
        "id": user.id, "phone": user.phone, "role": user.role.value, "token": user.token
    }}


@app.get("/api/stations")
async def list_stations(db: AsyncSession = Depends(get_db), user: Optional[User] = Depends(get_current_user)):
    from sqlalchemy import select
    query = select(Station).order_by(Station.id)
    if user and user.role == UserRole.OPERATOR:
        query = query.where(Station.operator_id == user.id)
    result = await db.execute(query)
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
            "operator_id": s.operator_id,
            "piles": [{
                "id": p.id, "pile_code": p.pile_code,
                "type": p.pile_type.value, "power": p.power,
                "status": p.status.value, "fault_code": p.fault_code,
            } for p in piles]
        })
    return {"success": True, "data": data}


@app.get("/api/stations/{station_id}")
async def get_station(
    station_id: int,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    from sqlalchemy import select
    station = await db.get(Station, station_id)
    if not station:
        raise HTTPException(404, "站点不存在")
    if user and user.role == UserRole.OPERATOR and station.operator_id != user.id:
        raise HTTPException(403, "无权查看该站点")
    result = await db.execute(select(Pile).where(Pile.station_id == station_id))
    piles = result.scalars().all()
    return {"success": True, "data": {
        "id": station.id, "name": station.name, "address": station.address,
        "latitude": station.latitude, "longitude": station.longitude,
        "operator_id": station.operator_id,
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
async def start_charging(
    req: StartChargingRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    from sqlalchemy import select
    if not user:
        raise HTTPException(401, "请先登录")
    if user.role != UserRole.OWNER:
        raise HTTPException(403, "仅车主角色可发起充电")
    if user.phone != req.phone:
        raise HTTPException(400, "只能使用自己的账号启动充电")
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
    asyncio.create_task(send_pile_command_fire_and_forget(req.pile_code, "start", phone=req.phone))
    pile.status = PileStatus.CHARGING
    now_ts = datetime.utcnow()
    order_no = f"OD{now_ts.strftime('%Y%m%d%H%M%S')}{now_ts.microsecond // 1000:03d}{pile.id:04d}"
    start_time = now_ts
    order = Order(
        order_no=order_no, user_phone=req.phone, user_id=user.id,
        pile_id=pile.id, start_time=start_time,
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
    return {"success": True, "data": {"order_no": order_no, "start_time": start_time.isoformat()}}


@app.post("/api/charging/stop")
async def stop_charging(
    req: StopChargingRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    from sqlalchemy import select
    if not user:
        raise HTTPException(401, "请先登录")
    result = await db.execute(select(Order).where(Order.order_no == req.order_no))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.user_phone != user.phone and user.role == UserRole.OWNER:
        raise HTTPException(403, "无权操作他人订单")
    if order.end_time:
        return {"success": True, "data": {
            "order_no": order.order_no,
            "energy_kwh": round(order.energy_kwh, 2),
            "energy_fee": round(order.energy_fee, 2),
            "service_fee": round(order.service_fee, 2),
            "total_fee": round(order.total_fee, 2),
            "start_time": order.start_time.isoformat() if order.start_time else None,
            "end_time": order.end_time.isoformat() if order.end_time else None,
            "payment_status": order.payment_status.value,
        }}
    pile = await db.get(Pile, order.pile_id)
    if pile:
        asyncio.create_task(send_pile_command_fire_and_forget(pile.pile_code, "stop"))
    start_t = order.start_time or datetime.utcnow()
    end_t = datetime.utcnow()
    duration_hours = max(0.05, (end_t - start_t).total_seconds() / 3600.0)
    power_kw = pile.power if pile else 7.0
    energy = round(max(0.3, order.energy_kwh if order.energy_kwh > 0 else power_kw * duration_hours), 2)
    energy_fee, service_fee, total_fee = billing_engine.calculate(start_t, end_t, energy)
    order.end_time = end_t
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
        "start_time": start_t.isoformat(),
        "end_time": end_t.isoformat(),
        "payment_status": PaymentStatus.PENDING.value,
    }}


@app.get("/api/orders/current")
async def get_current_order(
    phone: str,
    pile_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    from sqlalchemy import select
    if not user:
        raise HTTPException(401, "请先登录")
    if user.role == UserRole.OWNER and user.phone != phone:
        raise HTTPException(403, "无权查看他人订单")
    result = await db.execute(
        select(Order).where(
            Order.user_phone == phone, Order.end_time.is_(None)
        ).order_by(Order.id.desc()).limit(1)
    )
    order = result.scalar_one_or_none()
    if not order:
        return {"success": True, "data": None}
    pile = await db.get(Pile, order.pile_id)
    now = datetime.utcnow()
    duration = int((now - (order.start_time or now)).total_seconds())
    e_fee, s_fee, t_fee = billing_engine.calculate(
        order.start_time or now, now, order.energy_kwh
    )
    return {"success": True, "data": {
        "order_no": order.order_no,
        "pile_code": pile.pile_code if pile else "",
        "pile_power": pile.power if pile else 7.0,
        "start_time": order.start_time.isoformat() if order.start_time else None,
        "duration_seconds": duration,
        "energy_kwh": round(order.energy_kwh, 2),
        "energy_fee": round(e_fee, 2),
        "service_fee": round(s_fee, 2),
        "total_fee": round(t_fee, 2),
    }}


@app.get("/api/orders")
async def list_orders(
    phone: Optional[str] = None,
    station_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    exclude_cancelled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    from sqlalchemy import select
    if not user:
        raise HTTPException(401, "请先登录")
    query = select(Order).order_by(Order.id.desc()).limit(1000)
    conditions = []
    if user.role == UserRole.OWNER:
        conditions.append(Order.user_phone == user.phone)
    elif phone:
        conditions.append(Order.user_phone == phone)
    if start_date:
        try:
            conditions.append(Order.start_time >= datetime.fromisoformat(start_date))
        except ValueError:
            pass
    if end_date:
        try:
            conditions.append(Order.start_time <= datetime.fromisoformat(end_date))
        except ValueError:
            pass
    if exclude_cancelled:
        conditions.append(Order.payment_status != PaymentStatus.CANCELLED)
    if conditions:
        query = query.where(and_(*conditions))
    result = await db.execute(query)
    orders = result.scalars().all()
    pile_ids = list({o.pile_id for o in orders})
    piles: Dict[int, Pile] = {}
    if pile_ids:
        pr = await db.execute(select(Pile).where(Pile.id.in_(pile_ids)))
        for p in pr.scalars().all():
            piles[p.id] = p
    data = []
    for o in orders:
        p = piles.get(o.pile_id)
        if station_id and p and p.station_id != station_id:
            continue
        if user.role == UserRole.OPERATOR:
            if not p:
                continue
            st = await db.get(Station, p.station_id)
            if not st or st.operator_id != user.id:
                continue
        data.append({
            "id": o.id, "order_no": o.order_no,
            "user_phone": o.user_phone,
            "pile_code": p.pile_code if p else "",
            "station_id": p.station_id if p else None,
            "pile_type": p.pile_type.value if p else "",
            "start_time": o.start_time.isoformat() if o.start_time else None,
            "end_time": o.end_time.isoformat() if o.end_time else None,
            "energy_kwh": round(o.energy_kwh, 2),
            "energy_fee": round(o.energy_fee, 2),
            "service_fee": round(o.service_fee, 2),
            "total_fee": round(o.total_fee, 2),
            "payment_status": o.payment_status.value,
            "paid_at": o.paid_at.isoformat() if o.paid_at else None,
        })
    return {"success": True, "data": data}


@app.get("/api/orders/export")
async def export_orders(
    station_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(403, "无权导出")
    from sqlalchemy import select
    query = select(Order).order_by(Order.id.desc())
    conditions = []
    if start_date:
        try:
            conditions.append(Order.created_at >= datetime.fromisoformat(start_date))
        except ValueError:
            pass
    if end_date:
        try:
            conditions.append(Order.created_at <= datetime.fromisoformat(end_date))
        except ValueError:
            pass
    if conditions:
        query = query.where(and_(*conditions))
    result = await db.execute(query)
    orders = result.scalars().all()
    pile_ids = list({o.pile_id for o in orders})
    piles: Dict[int, Pile] = {}
    stations_map: Dict[int, Station] = {}
    if pile_ids:
        pr = await db.execute(select(Pile).where(Pile.id.in_(pile_ids)))
        for p in pr.scalars().all():
            piles[p.id] = p
            if p.station_id not in stations_map:
                stations_map[p.station_id] = await db.get(Station, p.station_id)
    status_text = {"paid": "已支付", "pending": "待支付", "cancelled": "已取消"}
    type_text = {"fast": "快充", "slow": "慢充"}
    rows = []
    for o in orders:
        p = piles.get(o.pile_id)
        st = stations_map.get(p.station_id) if p else None
        if station_id and (not p or p.station_id != station_id):
            continue
        if user.role == UserRole.OPERATOR and (not st or st.operator_id != user.id):
            continue
        rows.append([
            o.order_no,
            o.user_phone,
            st.name if st else "",
            p.pile_code if p else "",
            type_text.get(p.pile_type.value, "") if p else "",
            o.start_time.strftime("%Y-%m-%d %H:%M") if o.start_time else "",
            o.end_time.strftime("%Y-%m-%d %H:%M") if o.end_time else "",
            round(o.energy_kwh, 2),
            round(o.energy_fee, 2),
            round(o.service_fee, 2),
            round(o.total_fee, 2),
            status_text.get(o.payment_status.value, o.payment_status.value),
        ])
    if len(rows) == 0:
        from fastapi.responses import JSONResponse
        return JSONResponse({"success": True, "data": [], "empty": True, "message": "该条件下没有可导出的订单"})
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["订单号", "手机号", "站点名称", "桩编号", "桩类型",
                     "开始时间", "结束时间", "电量(度)", "电费", "服务费", "总费用", "支付状态"])
    for row in rows:
        writer.writerow(row)
    output.seek(0)
    csv_content = "\ufeff" + output.getvalue()
    filename = f"orders_{station_id or 'all'}_{datetime.now().strftime('%Y%m%d%H%M')}.csv"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"}
    return StreamingResponse(iter([csv_content]), media_type="text/csv; charset=utf-8", headers=headers)


@app.post("/api/orders/{order_no}/pay")
async def pay_order(
    order_no: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    from sqlalchemy import select
    if not user:
        raise HTTPException(401, "请先登录")
    result = await db.execute(select(Order).where(Order.order_no == order_no))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    if user.role == UserRole.OWNER and order.user_phone != user.phone:
        raise HTTPException(403, "无权支付他人订单")
    if order.payment_status == PaymentStatus.PAID:
        return {"success": True, "data": {"order_no": order_no, "paid": True, "total_fee": round(order.total_fee, 2)}}
    if order.payment_status == PaymentStatus.CANCELLED:
        raise HTTPException(400, "订单已取消，无法支付")
    order.payment_status = PaymentStatus.PAID
    order.paid_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "data": {
        "order_no": order_no,
        "total_fee": round(order.total_fee, 2),
        "paid_at": order.paid_at.isoformat(),
    }}


@app.post("/api/piles/command")
async def pile_command(
    req: PileCommandRequest,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_current_user)
):
    from sqlalchemy import select
    if not user or user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(403, "无权操作充电桩")
    result = await db.execute(select(Pile).where(Pile.pile_code == req.pile_code))
    pile = result.scalar_one_or_none()
    if not pile:
        raise HTTPException(404, "充电桩不存在")
    if user.role == UserRole.OPERATOR:
        station = await db.get(Station, pile.station_id)
        if not station or station.operator_id != user.id:
            raise HTTPException(403, "无权操作该充电桩")
    asyncio.create_task(send_pile_command_fire_and_forget(req.pile_code, req.command))
    if req.command == "reboot":
        if pile.status == PileStatus.FAULT:
            fault_pile_ids.add(pile.id)
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
    return {"success": True, "data": {"result": "sent"}}


def _get_time_range(period: str, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Tuple[datetime, datetime]:
    now = datetime.utcnow()
    today_start = datetime.combine(now.date(), datetime.min.time())
    if period == "custom":
        s = datetime.fromisoformat(start_date) if start_date else today_start
        e = datetime.fromisoformat(end_date) if end_date else now
        return s, e
    if period == "week":
        week_start = today_start - timedelta(days=now.weekday())
        return week_start, now
    elif period == "month":
        month_start = today_start.replace(day=1)
        return month_start, now
    return today_start, now


@app.get("/api/admin/dashboard")
def admin_dashboard(
    period: str = Query("day", pattern="^(day|week|month)$"),
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(403, "无权访问")
    range_start, range_end = _get_time_range(period)
    pile_q = db.query(Pile)
    station_q = db.query(Station)
    if user.role == UserRole.OPERATOR:
        station_q = station_q.filter(Station.operator_id == user.id)
        accessible_station_ids = [s.id for s in station_q.all()]
        pile_q = pile_q.filter(Pile.station_id.in_(accessible_station_ids)) if accessible_station_ids else pile_q.filter(Pile.station_id == -1)
    total_piles = pile_q.count()
    online = pile_q.filter(Pile.status != PileStatus.OFFLINE).count()
    charging = pile_q.filter(Pile.status == PileStatus.CHARGING).count()
    fault = pile_q.filter(Pile.status == PileStatus.FAULT).count()
    online_rate = round(online / total_piles * 100, 2) if total_piles > 0 else 0
    fault_rate = round(fault / total_piles * 100, 2) if total_piles > 0 else 0
    utilization = round(charging / online * 100, 2) if online > 0 else 0

    stations = station_q.all()
    station_stats = []
    fault_stations = []
    FAULT_WARN_THRESHOLD = 15
    for s in stations:
        piles = db.query(Pile).filter(Pile.station_id == s.id).all()
        if not piles:
            continue
        sc = sum(1 for p in piles if p.status == PileStatus.CHARGING)
        fc = sum(1 for p in piles if p.status == PileStatus.FAULT)
        util_pct = round(sc / len(piles) * 100, 2)
        fault_pct = round(fc / len(piles) * 100, 2)
        station_stats.append({"id": s.id, "name": s.name, "utilization": util_pct, "fault_rate": fault_pct, "fault_count": fc, "total": len(piles)})
        if fault_pct >= FAULT_WARN_THRESHOLD or fc >= 2:
            fault_stations.append({"id": s.id, "name": s.name, "fault_count": fc, "total": len(piles), "fault_rate": fault_pct})
    station_stats.sort(key=lambda x: x["utilization"], reverse=True)
    fault_stations.sort(key=lambda x: x["fault_rate"], reverse=True)

    trend_data = []
    orders_range = db.query(Order).filter(
        Order.start_time >= range_start, Order.start_time <= range_end
    ).all()
    if period == "day":
        for h in range(24):
            start = range_start + timedelta(hours=h)
            end = start + timedelta(hours=1)
            bucket = [o for o in orders_range if o.start_time and start <= o.start_time < end]
            energy = sum(o.energy_kwh for o in bucket)
            revenue = sum(o.total_fee for o in bucket if o.payment_status != PaymentStatus.CANCELLED)
            trend_data.append({"label": f"{h}时", "energy_kwh": round(energy, 2), "revenue": round(revenue, 2), "orders": len(bucket)})
    elif period == "week":
        for d in range(7):
            start = range_start + timedelta(days=d)
            end = start + timedelta(days=1)
            bucket = [o for o in orders_range if o.start_time and start <= o.start_time < end]
            energy = sum(o.energy_kwh for o in bucket)
            revenue = sum(o.total_fee for o in bucket if o.payment_status != PaymentStatus.CANCELLED)
            trend_data.append({"label": ["周一","周二","周三","周四","周五","周六","周日"][d], "energy_kwh": round(energy, 2), "revenue": round(revenue, 2), "orders": len(bucket)})
    else:
        num_days = (range_end - range_start).days + 1
        for d in range(num_days):
            start = range_start + timedelta(days=d)
            end = start + timedelta(days=1)
            bucket = [o for o in orders_range if o.start_time and start <= o.start_time < end]
            energy = sum(o.energy_kwh for o in bucket)
            revenue = sum(o.total_fee for o in bucket if o.payment_status != PaymentStatus.CANCELLED)
            trend_data.append({"label": f"{d+1}日", "energy_kwh": round(energy, 2), "revenue": round(revenue, 2), "orders": len(bucket)})

    total_orders = len(orders_range)
    total_energy = sum(o.energy_kwh for o in orders_range)
    total_revenue = sum(o.total_fee for o in orders_range if o.payment_status == PaymentStatus.PAID)

    wo_query = db.query(WorkOrder)
    if user.role == UserRole.OPERATOR:
        wo_query = wo_query.filter(WorkOrder.station_id.in_(accessible_station_ids)) if accessible_station_ids else wo_query.filter(WorkOrder.station_id == -1)
    pending_wo = wo_query.filter(WorkOrder.status == WorkOrderStatus.PENDING).count()
    processing_wo = wo_query.filter(WorkOrder.status == WorkOrderStatus.PROCESSING).count()
    resolved_wo = wo_query.filter(WorkOrder.status == WorkOrderStatus.RESOLVED).count()

    return {"success": True, "data": {
        "period": period,
        "total_piles": total_piles,
        "online_piles": online,
        "online_rate": online_rate,
        "fault_count": fault,
        "fault_rate": fault_rate,
        "charging_count": charging,
        "utilization": utilization,
        "top_utilization_stations": station_stats[:10],
        "fault_warning_stations": fault_stations,
        "trend": trend_data,
        "period_orders": total_orders,
        "period_energy": round(total_energy, 2),
        "period_revenue": round(total_revenue, 2),
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "work_order_stats": {
            "pending": pending_wo,
            "processing": processing_wo,
            "resolved": resolved_wo,
        },
    }}


@app.get("/api/billing/rules")
def list_billing_rules(
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role != UserRole.ADMIN:
        raise HTTPException(403, "无权查看计费规则")
    rules = db.query(BillingRule).filter(BillingRule.is_active == True).all()
    return {"success": True, "data": [
        {"id": r.id, "period_name": r.period_name,
         "start_hour": r.start_hour, "end_hour": r.end_hour,
         "price_per_kwh": r.price_per_kwh} for r in rules
    ]}


@app.post("/api/billing/rules")
def create_billing_rule(
    rule: BillingRuleCreate,
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role != UserRole.ADMIN:
        raise HTTPException(403, "无权配置计费规则")
    new_rule = BillingRule(**rule.model_dump(), is_active=True)
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return {"success": True, "data": {"id": new_rule.id}}


@app.get("/api/work-orders")
def list_work_orders(
    station_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(403, "无权查看工单")
    query = db.query(WorkOrder).order_by(WorkOrder.id.desc())
    if user.role == UserRole.OPERATOR:
        accessible_station_ids = [s.id for s in db.query(Station).filter(Station.operator_id == user.id).all()]
        query = query.filter(WorkOrder.station_id.in_(accessible_station_ids)) if accessible_station_ids else query.filter(WorkOrder.station_id == -1)
    if station_id:
        query = query.filter(WorkOrder.station_id == station_id)
    if status:
        status_enum = None
        try:
            status_enum = WorkOrderStatus(status)
        except ValueError:
            pass
        if status_enum:
            query = query.filter(WorkOrder.status == status_enum)
    wos = query.all()
    pile_ids = [w.pile_id for w in wos]
    piles = {p.id: p for p in db.query(Pile).filter(Pile.id.in_(pile_ids)).all()} if pile_ids else {}
    stations = {s.id: s for s in db.query(Station).all()}
    data = []
    for w in wos:
        p = piles.get(w.pile_id)
        st = stations.get(w.station_id)
        data.append({
            "id": w.id,
            "order_no": w.order_no,
            "pile_id": w.pile_id,
            "pile_code": p.pile_code if p else "",
            "station_id": w.station_id,
            "station_name": st.name if st else "",
            "fault_code": w.fault_code,
            "fault_description": w.fault_description,
            "status": w.status.value,
            "handler_name": w.handler_name or "",
            "result": w.result or "",
            "resolved_at": w.resolved_at.isoformat() if w.resolved_at else None,
            "created_at": w.created_at.isoformat() if w.created_at else None,
            "updated_at": w.updated_at.isoformat() if w.updated_at else None,
        })
    return {"success": True, "data": data}


@app.get("/api/work-orders/stats")
def work_order_stats(
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(403, "无权查看")
    query = db.query(WorkOrder)
    if user.role == UserRole.OPERATOR:
        accessible_station_ids = [s.id for s in db.query(Station).filter(Station.operator_id == user.id).all()]
        query = query.filter(WorkOrder.station_id.in_(accessible_station_ids)) if accessible_station_ids else query.filter(WorkOrder.station_id == -1)
    pending = query.filter(WorkOrder.status == WorkOrderStatus.PENDING).count()
    processing = query.filter(WorkOrder.status == WorkOrderStatus.PROCESSING).count()
    resolved = query.filter(WorkOrder.status == WorkOrderStatus.RESOLVED).count()
    closed = query.filter(WorkOrder.status == WorkOrderStatus.CLOSED).count()
    return {"success": True, "data": {
        "pending": pending,
        "processing": processing,
        "resolved": resolved,
        "closed": closed,
        "total": pending + processing + resolved + closed
    }}


@app.post("/api/work-orders")
def create_work_order(
    req: CreateWorkOrderRequest,
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(403, "无权创建工单")
    pile = db.query(Pile).filter(Pile.pile_code == req.pile_code).first()
    if not pile:
        raise HTTPException(404, "充电桩不存在")
    if user.role == UserRole.OPERATOR:
        station = db.query(Station).filter(Station.id == pile.station_id).first()
        if not station or station.operator_id != user.id:
            raise HTTPException(403, "无权为该桩创建工单")
    now_wo = datetime.utcnow()
    order_no = f"WO{now_wo.strftime('%Y%m%d%H%M%S')}{now_wo.microsecond // 1000:03d}{pile.id:04d}"
    wo = WorkOrder(
        order_no=order_no,
        pile_id=pile.id,
        station_id=pile.station_id,
        fault_code=req.fault_code or pile.fault_code,
        fault_description=req.fault_description,
        status=WorkOrderStatus.PENDING,
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return {"success": True, "data": {"id": wo.id, "order_no": wo.order_no}}


@app.post("/api/work-orders/{wo_id}/handle")
def handle_work_order(
    wo_id: int,
    req: HandleWorkOrderRequest,
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        raise HTTPException(403, "无权处理工单")
    wo = db.query(WorkOrder).filter(WorkOrder.id == wo_id).first()
    if not wo:
        raise HTTPException(404, "工单不存在")
    if user.role == UserRole.OPERATOR:
        station = db.query(Station).filter(Station.id == wo.station_id).first()
        if not station or station.operator_id != user.id:
            raise HTTPException(403, "无权处理该工单")
    wo.status = req.status
    wo.handler_id = user.id
    wo.handler_name = user.phone
    wo.result = req.result
    if req.status in (WorkOrderStatus.RESOLVED, WorkOrderStatus.CLOSED):
        wo.resolved_at = datetime.utcnow()
    db.commit()
    return {"success": True, "data": {"id": wo.id, "status": wo.status.value}}


@app.get("/api/revenue/analysis")
def revenue_analysis(
    period: str = Query("day", pattern="^(day|week|month|custom)$"),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    group_by: str = Query("station", pattern="^(station|pile_type)$"),
    station_id: Optional[int] = None,
    db: Session = Depends(get_sync_db),
    user: Optional[User] = Depends(get_current_user)
):
    if not user or user.role != UserRole.ADMIN:
        raise HTTPException(403, "无权查看收入分析")
    range_start, range_end = _get_time_range(period, start_date, end_date)
    query = db.query(Order).filter(
        Order.start_time >= range_start,
        Order.start_time <= range_end,
        Order.payment_status != PaymentStatus.CANCELLED,
    )
    if station_id:
        subq = db.query(Pile.id).filter(Pile.station_id == station_id).subquery()
        query = query.filter(Order.pile_id.in_(subq))
    orders = query.all()
    pile_ids = [o.pile_id for o in orders]
    piles = {p.id: p for p in db.query(Pile).filter(Pile.id.in_(pile_ids)).all()} if pile_ids else {}
    stations = {s.id: s for s in db.query(Station).all()}
    groups: Dict[str, Dict] = {}
    for o in orders:
        p = piles.get(o.pile_id)
        if not p:
            continue
        if group_by == "station":
            key = str(p.station_id)
            name = stations.get(p.station_id).name if stations.get(p.station_id) else "未知"
        else:
            key = p.pile_type.value
            name = "快充" if p.pile_type == PileType.FAST else "慢充"
        if key not in groups:
            groups[key] = {
                "key": key,
                "name": name,
                "orders": 0,
                "energy_kwh": 0.0,
                "revenue": 0.0,
                "station_id": p.station_id if group_by == "station" else None,
            }
        groups[key]["orders"] += 1
        groups[key]["energy_kwh"] += o.energy_kwh
        groups[key]["revenue"] += o.total_fee
    result = []
    for g in groups.values():
        avg_price = round(g["revenue"] / g["orders"], 2) if g["orders"] > 0 else 0
        result.append({
            **g,
            "energy_kwh": round(g["energy_kwh"], 2),
            "revenue": round(g["revenue"], 2),
            "avg_price": avg_price,
        })
    result.sort(key=lambda x: x["revenue"], reverse=True)
    total_orders = sum(g["orders"] for g in result)
    total_energy = sum(g["energy_kwh"] for g in result)
    total_revenue = sum(g["revenue"] for g in result)
    avg_price_total = round(total_revenue / total_orders, 2) if total_orders > 0 else 0
    return {"success": True, "data": {
        "period": period,
        "group_by": group_by,
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "total_orders": total_orders,
        "total_energy": round(total_energy, 2),
        "total_revenue": round(total_revenue, 2),
        "avg_price": avg_price_total,
        "items": result,
    }}


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
