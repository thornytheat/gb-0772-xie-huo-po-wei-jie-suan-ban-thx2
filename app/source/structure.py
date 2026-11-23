from dataclasses import dataclass
from datetime import datetime
import re

from app.billing.ratebook import RateBook, build_ratebook
from app.curb.timeaxis import M, minute
from app.problems import DocketError

SCHEMAS={
    'sensors':'event,berth,plate,sensor,start,end',
    'bookings':'reservation,berth,plate,effective,start,end,state',
    'payments':'receipt,berth,plate,arrival,cents',
}


@dataclass(frozen=True)
class Survey:
    name: str
    start: datetime
    end: datetime
    berths: tuple[str,...]
    ratebook: RateBook

    @classmethod
    def build(cls, obj):
        try:
            start,end=minute(obj['start']),minute(obj['end'])
            name=obj['name']
            ids=obj['berths']
            if (not isinstance(name,str) or not name.strip() or len(name)>70 or not start<end<=start+2880*M
                or not isinstance(ids,list) or not 1<=len(ids)<=12 or any(
                    not isinstance(x,str) or not re.fullmatch(r'[A-Z0-9-]{1,20}',x) for x in ids)
                or len(set(ids))!=len(ids)):
                raise ValueError
        except (KeyError,TypeError,ValueError):
            raise DocketError('SURVEY_BAD','清算区间或泊位列表错误') from None
        # 费率版本表缺失时退化为单版本，旧原件无需改造即可继续清算。
        ratebook=build_ratebook(obj['rates']) if 'rates' in obj else None
        return cls(name,start,end,tuple(ids),ratebook)
