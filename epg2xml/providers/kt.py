import logging
import re
from datetime import date, datetime, timedelta
from typing import List
from urllib.parse import unquote

from bs4 import SoupStrainer

from epg2xml.providers import EPGProgram, EPGProvider, no_endtime
from epg2xml.utils import ParserBeautifulSoup as BeautifulSoup

log = logging.getLogger(__name__.rsplit(".", maxsplit=1)[-1].upper())

CH_CATE = [
    # 0은 전체 채널
    {"id": "1", "name": "UHD"},
    {"id": "3", "name": "홍보"},
    {"id": "4", "name": "지상파"},
    {"id": "5", "name": "홈쇼핑"},
    {"id": "6", "name": "종합편성"},
    {"id": "8", "name": "드라마/버라이어티"},
    {"id": "10", "name": "오락/음악"},
    {"id": "12", "name": "영화/시리즈"},
    {"id": "137", "name": "스포츠"},
    {"id": "206", "name": "취미/레저"},
    {"id": "317", "name": "애니/유아"},
    {"id": "442", "name": "교육"},
    {"id": "446", "name": "다큐/교양"},
    {"id": "447", "name": "뉴스/경제"},
    {"id": "448", "name": "공공/공익/정보"},
    {"id": "449", "name": "종교"},
    {"id": "491", "name": "오픈채널"},
    {"id": "507", "name": "유료"},
    {"id": "508", "name": "오디오"},
]
PTN_RATING = re.compile(r"([\d,]+)")


class KT(EPGProvider):
    """EPGProvider for KT

    데이터: rawhtml
    요청수: #channels * #days
    특이사항:
    - 가끔 업데이트 지연
    - 프로그램 시작 시각만 제공
    """

    referer = "https://tv.kt.com/"
    title_regex = r"^(?P<title>.*?)\s?([\<\(]?(?P<part>\d+)부[\>\)]?)?$"

    def get_svc_channels(self) -> List[dict]:
        svc_channels = []
        url = "https://tv.kt.com/tv/channel/pChList.asp"
        params = {"ch_type": "1", "parent_menu_id": "0"}
        for c in CH_CATE:
            params.update({"parent_menu_id": c["id"]})
            soup = BeautifulSoup(self.request(url, method="POST", data=params))
            
            # 채널 목록에서 채널 정보와 로고 URL 추출
            for channel_item in soup.select("li > a"):
                try:
                    # 채널 번호와 이름 추출
                    ch_text = unquote(channel_item.find("span", {"class": "ch"}).text.strip())
                    ch_parts = ch_text.split()
                    
                    if len(ch_parts) < 2:
                        continue
                    
                    ch_no = ch_parts[0]
                    ch_name = " ".join(ch_parts[1:])
                    
                    # 채널 로고 URL 추출 (img 태그에서)
                    icon_url = None
                    img_tag = channel_item.find("img")
                    if img_tag and img_tag.get("src"):
                        icon_url = img_tag["src"]
                        # 상대 URL을 절대 URL로 변환
                        if icon_url.startswith("/"):
                            icon_url = "https://tv.kt.com" + icon_url
                        elif not icon_url.startswith("http"):
                            icon_url = "https://tv.kt.com/" + icon_url
                    
                    channel_data = {
                        "Name": ch_name,
                        "No": str(ch_no),
                        "ServiceId": ch_no,
                        "Category": c["name"],
                    }
                    
                    # Icon URL이 있으면 추가
                    if icon_url:
                        channel_data["Icon_url"] = icon_url
                    
                    svc_channels.append(channel_data)
                    
                except Exception as e:
                    log.debug("채널 파싱 중 오류 (무시): %s", e)
                    continue
                    
        return svc_channels

    @no_endtime
    def get_programs(self) -> None:
        url = "https://tv.kt.com/tv/channel/pSchedule.asp"
        params = {
            "ch_type": "1",  # 1: live 2: skylife 3: uhd live 4: uhd skylife
            "view_type": "1",  # 1: daily 2: weekly
            "service_ch_no": "SVCID",
            "seldate": "EPGDATE",
        }
        for idx, _ch in enumerate(self.req_channels):
            log.info("%03d/%03d %s", idx + 1, len(self.req_channels), _ch)
            for nd in range(int(self.cfg["FETCH_LIMIT"])):
                day = date.today() + timedelta(days=nd)
                params.update({"service_ch_no": _ch.svcid, "seldate": day.strftime("%Y%m%d")})
                data = self.request(url, method="POST", data=params)
                try:
                    _epgs = self.__epgs_of_day(_ch.id, data, day)
                except Exception:
                    log.exception("프로그램 파싱 중 예외: %s, %s", _ch, day)
                else:
                    _ch.programs.extend(_epgs)

    def __epgs_of_day(self, channelid: str, data: str, day: datetime) -> List[EPGProgram]:
        _epgs = []
        soup = BeautifulSoup(unquote(data), parse_only=SoupStrainer("tbody"))
        for row in soup.find_all("tr"):
            cell = row.find_all("td")
            hour = cell[0].text.strip()
            for minute, program, category in zip(*[c.find_all("p") for c in cell[1:]]):
                _epg = EPGProgram(channelid)
                _epg.stime = datetime.strptime(f"{day} {hour}:{minute.text.strip()}", "%Y-%m-%d %H:%M")
                _epg.title = program.text.replace("방송중 ", "").strip()
                if m := self.title_regex.match(_epg.title):
                    _epg.title = m.group("title")
                    if part_num := m.group("part"):
                        _epg.part_num = part_num
                        _epg.title += f" ({_epg.part_num}부)"
                _epg.categories = [category.text.strip()]
                for image in program.find_all("img", alt=True):
                    if "시청 가능" not in (alt := image["alt"]):
                        continue
                    grade = PTN_RATING.match(alt)
                    _epg.rating = int(grade.group(1)) if grade else 0
                _epgs.append(_epg)
        return _epgs
