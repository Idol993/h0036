from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Tuple, Optional


@dataclass
class TimePeriod:
    name: str
    start_hour: int
    end_hour: int
    price_per_kwh: float


@dataclass
class BillingConfig:
    periods: List[TimePeriod] = field(default_factory=list)
    default_price: float = 0.9
    service_fee_per_kwh: float = 0.8

    def __post_init__(self):
        if not self.periods:
            self.periods = [
                TimePeriod("峰时", 10, 15, 1.5),
                TimePeriod("峰时", 18, 21, 1.5),
                TimePeriod("谷时", 23, 7, 0.4),
            ]


class BillingEngine:
    def __init__(self, config: Optional[BillingConfig] = None):
        self.config = config or BillingConfig()

    def _hour_in_period(self, hour: int, period: TimePeriod) -> bool:
        start, end = period.start_hour, period.end_hour
        if start < end:
            return start <= hour < end
        else:
            return hour >= start or hour < end

    def _get_price_for_hour(self, hour: int) -> float:
        for p in self.config.periods:
            if self._hour_in_period(hour, p):
                return p.price_per_kwh
        return self.config.default_price

    def _split_charging_segments(
        self, start_time: datetime, end_time: datetime, total_kwh: float
    ) -> List[Tuple[datetime, datetime, float]]:
        if end_time <= start_time:
            return []
        total_seconds = (end_time - start_time).total_seconds()
        if total_seconds <= 0:
            return []

        segments = []
        current = start_time
        while current < end_time:
            hour_start = current.replace(minute=0, second=0, microsecond=0)
            next_hour = hour_start + timedelta(hours=1)
            segment_end = min(next_hour, end_time)
            segment_seconds = (segment_end - current).total_seconds()
            segment_kwh = total_kwh * (segment_seconds / total_seconds)
            segments.append((current, segment_end, segment_kwh))
            current = next_hour
        return segments

    def calculate(
        self, start_time: datetime, end_time: datetime, total_kwh: float
    ) -> Tuple[float, float, float]:
        if total_kwh <= 0:
            return 0.0, 0.0, 0.0

        segments = self._split_charging_segments(start_time, end_time, total_kwh)
        energy_fee = 0.0

        for seg_start, seg_end, seg_kwh in segments:
            hour = seg_start.hour
            price = self._get_price_for_hour(hour)
            energy_fee += seg_kwh * price

        service_fee = total_kwh * self.config.service_fee_per_kwh
        total_fee = energy_fee + service_fee

        return round(energy_fee, 2), round(service_fee, 2), round(total_fee, 2)

    def calculate_detail(
        self, start_time: datetime, end_time: datetime, total_kwh: float
    ) -> dict:
        if total_kwh <= 0:
            return {
                "energy_fee": 0.0, "service_fee": 0.0,
                "total_fee": 0.0, "segments": []
            }

        segments = self._split_charging_segments(start_time, end_time, total_kwh)
        energy_fee = 0.0
        detail_segments = []

        for seg_start, seg_end, seg_kwh in segments:
            hour = seg_start.hour
            price = self._get_price_for_hour(hour)
            seg_fee = seg_kwh * price
            energy_fee += seg_fee
            period_name = "平时"
            for p in self.config.periods:
                if self._hour_in_period(hour, p):
                    period_name = p.name
                    break
            detail_segments.append({
                "period": period_name,
                "start": seg_start.isoformat(),
                "end": seg_end.isoformat(),
                "kwh": round(seg_kwh, 4),
                "price": price,
                "fee": round(seg_fee, 2),
            })

        service_fee = total_kwh * self.config.service_fee_per_kwh
        total_fee = energy_fee + service_fee

        return {
            "energy_fee": round(energy_fee, 2),
            "service_fee": round(service_fee, 2),
            "total_fee": round(total_fee, 2),
            "segments": detail_segments,
        }

    def update_periods(self, periods: List[TimePeriod]):
        self.config.periods = periods

    def update_service_fee(self, fee_per_kwh: float):
        self.config.service_fee_per_kwh = fee_per_kwh

    def update_default_price(self, price: float):
        self.config.default_price = price
