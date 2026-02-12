import logging
from datetime import date, datetime, timedelta
from typing import List

from epg2xml.providers import EPGProgram, EPGProvider, no_endtime

log = logging.getLogger(__name__.rsplit(".", maxsplit=1)[-1].upper())
today = date.today()


class SBS(EPGProvider):
    """EPGProvider for SBS
    
    데이터: JSON API
    요청수: 1 (채널 목록) + N (일자별 편성표)
    특이사항:
    - 채널 목록: apis.sbs.co.kr/play-api/1.0/onair/channels
    - 편성표: static.cloud.sbs.co.kr/schedule/{year}/{month}/{date}/{channel_json_id}.json
    - 채널명과 JSON ID 매핑 필요 (예: S01 -> SBS, S03 -> Plus)
    """
    
    referer = "https://www.sbs.co.kr/"
    tps = 2.0
    
    # 온에어 채널 ID를 편성표 JSON ID로 매핑
    CHANNEL_MAPPING = {
        "S01": "SBS",        # SBS
        "S03": "Plus",       # SBS Plus
        "S04": "ETV",        # SBS funE (구 SBS E)
        "S02": "ESPN",       # SBS Sports
        "S05": "Golf",       # SBS Golf
        "S12": "Golf2",      # SBS Golf2
        "S06": "CNBC",       # SBS Biz (구 SBS CNBC)
        "S11": "Fil",        # SBS Life (구 SBS Fil)
        "S07": "Power",      # SBS 파워FM
        "S08": "Love",       # SBS 러브FM
        "S19": "DMB+Radio",  # SBS 고릴라M (구 SBS DMB+Radio)
    }
    
    # iptv-org 채널 로고 URL 매핑 (고품질 PNG)
    CHANNEL_LOGO_MAP = {
        "S01": "https://i.imgur.com/4LHX71N.png",  # SBS
        "S02": "https://i.imgur.com/L2SdLkb.png",  # SBS Sports
        "S03": "https://i.imgur.com/8pINOIM.png",  # SBS Plus
        "S04": "https://i.imgur.com/sxM1XcA.png",  # SBS funE
        "S05": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3d/SBS_Golf_logo_2018.svg/512px-SBS_Golf_logo_2018.svg.png",  # SBS Golf
        "S06": "https://i.imgur.com/gwA98UT.png",  # SBS Biz
        "S11": "https://i.imgur.com/JKNSd8s.png",  # SBS Life
        # S07 (파워FM), S08 (러브FM), S12 (Golf2), S19 (고릴라M)는 로고 정보 없음
    }
    
    def get_svc_channels(self) -> List[dict]:
        """온에어 채널 목록 조회"""
        url = "https://apis.sbs.co.kr/play-api/1.0/onair/channels"
        data = self.request(url)
        
        if not data or not isinstance(data, dict):
            log.error("채널 목록을 가져올 수 없습니다.")
            return []
        
        # API 응답 구조: {"list": [...]}
        channel_list = data.get("list", [])
        if not channel_list:
            log.error("채널 목록이 비어있습니다.")
            return []
        
        channels = []
        for item in channel_list:
            channel_id = item.get("channelid", "")
            
            # 편성표 JSON ID가 있는 채널만 포함
            if channel_id not in self.CHANNEL_MAPPING:
                log.debug("편성표가 없는 채널 제외: %s (%s)", item.get("channelname"), channel_id)
                continue
            
            # 채널 로고 URL (CHANNEL_LOGO_MAP에서 가져오기)
            logo_url = self.CHANNEL_LOGO_MAP.get(channel_id)
            
            channels.append({
                "Name": item.get("channelname", "").strip(),
                "Icon_url": logo_url,  # 로고가 없으면 None
                "ServiceId": channel_id,
                "Category": item.get("category", "").strip() or None,
            })
        
        log.info("총 %d개의 채널을 찾았습니다.", len(channels))
        return channels
    
    def __get_epg_url(self, channel_id: str, target_date: date) -> str:
        """특정 날짜와 채널의 편성표 URL 생성"""
        json_id = self.CHANNEL_MAPPING.get(channel_id)
        if not json_id:
            return None
        
        year = target_date.year
        month = target_date.month
        day = target_date.day
        
        return f"https://static.cloud.sbs.co.kr/schedule/{year}/{month}/{day}/{json_id}.json"
    
    def __parse_time(self, date_str: str, time_str: str) -> datetime:
        """날짜와 시간 문자열을 datetime으로 변환
        
        Args:
            date_str: "2026-01-20" 형식의 날짜
            time_str: "14:00" 또는 "24:10" 형식의 시간 (24시간 이후도 지원)
        
        Returns:
            datetime 객체
        """
        try:
            # 빈 문자열이나 None 체크
            if not time_str or not time_str.strip():
                # log.debug(f"빈 시간 문자열: {date_str} (정상: 종료시간 자동보정)")
                return None
            
            # 시간 문자열에서 시와 분 분리
            parts = time_str.strip().split(":")
            if len(parts) != 2:
                log.error("잘못된 시간 형식: %s %s", date_str, time_str)
                return None
            
            hour_str, minute_str = parts
            hour = int(hour_str)
            minute = int(minute_str)
            
            # 24시간 이후의 경우 (24:00, 25:00 등) 날짜를 하루 추가하고 시간 조정
            if hour >= 24:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                dt += timedelta(days=1)  # 다음날로 이동
                dt = dt.replace(hour=hour - 24, minute=minute)
            else:
                dt_str = f"{date_str} {time_str}"
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            
            return dt
        except (ValueError, TypeError) as e:
            log.error("시간 파싱 오류: %s %s - %s", date_str, time_str, e)
            return None
    
    def __epg_of_program(self, channelid: str, data: dict, target_date: date) -> EPGProgram:
        """편성표 항목을 EPGProgram 객체로 변환"""
        _epg = EPGProgram(channelid)
        
        date_str = target_date.strftime("%Y-%m-%d")
        
        # 시작/종료 시간
        start_time_str = data.get("start_time", "")
        end_time_str = data.get("end_time", "")
        
        _epg.stime = self.__parse_time(date_str, start_time_str)
        _epg.etime = self.__parse_time(date_str, end_time_str)

        
        # 시작 시간보다 종료 시간이 빠른 경우 (자정 넘김), 종료 시간에 하루 추가
        if _epg.stime and _epg.etime and _epg.etime <= _epg.stime:
            _epg.etime += timedelta(days=1)
        
        # 제목
        _epg.title = data.get("title", "").strip()
        
        # 시청 등급
        target_age = data.get("target_age", "0")
        try:
            _epg.rating = 0 if target_age == "0" else int(target_age)
        except (ValueError, TypeError):
            _epg.rating = 0
        
        # 프로그램 이미지 (포스터)
        program_image = data.get("program_image", "").strip()
        if program_image:
            _epg.poster_url = program_image
        
        # 추가 정보 (필요시 확장 가능)
        # homepage_url, programId 등의 정보가 있지만 EPGProgram에 직접 매핑되는 필드가 없음
        
        return _epg
    
    @no_endtime
    def get_programs(self) -> None:
        """모든 요청 채널의 편성표 조회"""
        for idx, _ch in enumerate(self.req_channels):
            log.info("%03d/%03d %s", idx + 1, len(self.req_channels), _ch)
            
            # 각 날짜별로 편성표 조회
            for nd in range(int(self.cfg["FETCH_LIMIT"])):
                target_date = today + timedelta(days=nd)
                epg_url = self.__get_epg_url(_ch.svcid, target_date)
                
                if not epg_url:
                    log.warning("편성표 URL을 생성할 수 없습니다: %s", _ch.svcid)
                    continue
                
                data = self.request(epg_url)
                
                if not data:
                    log.warning("편성표를 가져올 수 없습니다: %s (%s)", _ch.name, target_date)
                    continue
                
                if not isinstance(data, list):
                    log.error("잘못된 편성표 형식: %s (%s)", _ch.name, target_date)
                    continue
                
                # 각 프로그램 파싱
                for program_data in data:
                    try:
                        _epg = self.__epg_of_program(_ch.id, program_data, target_date)
                        if _epg.stime:  # 유효한 시작 시간이 있는 경우만 추가
                            _ch.programs.append(_epg)
                    except Exception:
                        log.exception("프로그램 파싱 중 예외: %s", _ch)
                
                log.debug("%s (%s): %d개 프로그램 추가", _ch.name, target_date, len(data))
