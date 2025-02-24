from selenium import webdriver as wb
from selenium.webdriver.common.by import By
import time
import os
import pandas as pd
import sqlite3
import schedule
from datetime import datetime
import pytz

# Flight 클래스는 그대로 사용
class Flight:
    def __init__(self, flight_name1, flight_time_s1, flight_time_e1, flight_name2, flight_time_s2, flight_time_e2, flight_cost):
        self.flight_name1 = flight_name1
        self.flight_time_s1 = flight_time_s1
        self.flight_time_e1 = flight_time_e1
        self.flight_name2 = flight_name2
        self.flight_time_s2 = flight_time_s2
        self.flight_time_e2 = flight_time_e2
        self.flight_cost = flight_cost  # "원 단위" 정수 문자열로 저장할 예정

    def show_flight(self):
        print(f"flight_name1: {self.flight_name1}")
        print(f"flight_time_s1: {self.flight_time_s1}")
        print(f"flight_time_e1: {self.flight_time_e1}")
        print(f"flight_name2: {self.flight_name2}")
        print(f"flight_time_s2: {self.flight_time_s2}")
        print(f"flight_time_e2: {self.flight_time_e2}")
        print(f"flight_cost: {self.flight_cost}")

def fetch_flight_info_for_schedule(sched):
    """
    사용자가 입력한 일정(sched: dictionary)에 기반하여 네이버 항공권 검색을 수행하고,
    결과를 flight_results 테이블에 저장하는 함수.
    
    수정 사항:
      - flight_cost 문자열에서 '₩', ',' 등을 제거해 순수 숫자(원 단위)만 남기고 DB에 저장.
      - 유저 ID 당 몇 번째 스케줄인지 계산하여 터미널 메시지 출력
      - 예: ID:123 / info:1 항공권 정보 저장 완료.
    """
    # 검색 파라미터 설정 (국제선 가정)
    inter_or_domestic = "international"
    start = sched['departure']       # 예: "SEL"
    end = sched['destination']       # 예: "TPE"
    start_date = sched['departure_date']  # "YYYYMMDD"
    end_date = sched['return_date']       # "YYYYMMDD"
    adult = sched['adult_count']
    child = sched['child_count']
    infant = sched['infant_count']
    Type = sched['seat_type'].upper()  # DB에 저장된 'y', 'p' 등을 'Y', 'P'로 변환


    url = f"https://flight.naver.com/flights/{inter_or_domestic}/{start}-{end}-{start_date}/{end}-{start}-{end_date}?adult={adult}&child={child}&infant={infant}&fareType={Type}"
    
    # Selenium을 위한 옵션 설정 및 브라우저 실행
    chrome_options = wb.ChromeOptions()
    chrome_options.add_argument("--headless")
    driver = wb.Chrome(options=chrome_options)
    driver.get(url)
    
    # 페이지 로딩 대기 (필요에 따라 조정)
    time.sleep(20)
    
    # 프로모션 관련 버튼 클릭 (요소 선택자는 실제 페이지 구조에 따라 수정)
    try:
        card_promotion_select = driver.find_element(By.CSS_SELECTOR,
            "div.international_content__Vpjrs > div > div.header_InternationalHeader___uXXU.header_is_concurrent__OBqXQ > div > div:nth-child(3) > button")
        card_promotion_select.click()
        time.sleep(2)
        card_without_button = driver.find_element(By.CSS_SELECTOR,
            "div.international_content__Vpjrs > div > div.header_InternationalHeader___uXXU.header_is_concurrent__OBqXQ > div > div:nth-child(3) > div > button:nth-child(2) > span")
        card_without_button.click()
        time.sleep(2)
    except Exception as e:
        print("프로모션 버튼 클릭 실패:", e)
    
    # 항공권 정보 추출
    flights = driver.find_elements(By.CSS_SELECTOR, "div.concurrent_ConcurrentList__pF_Kv > .concurrent_ConcurrentItemContainer__NDJda")
    flight_list = []
    num = 1
    for f in flights:
        try:
            names = f.find_elements(By.CSS_SELECTOR, ".airline_name__0Tw5w")
            if len(names) >= 2:
                flight_name1 = names[0].text
                flight_name2 = names[1].text
            else:
                flight_name1 = names[0].text
                flight_name2 = names[0].text

            times_ = f.find_elements(By.CSS_SELECTOR, ".route_time__xWu7a")
            flight_cost_raw = f.find_element(By.CSS_SELECTOR, ".item_num__aKbk4").text
            # 예: flight_cost_raw = "₩260,309"

            # 쉼표, ₩ 제거 후 -> int 변환, 다시 문자열로
            cost_str = flight_cost_raw.replace("₩", "").replace(",", "").strip()  # "260309"
            try:
                cost_int = int(cost_str)  # 260309
            except:
                cost_int = -1  # 잘못된 값 처리를 위해

            normalized_cost_str = str(cost_int)  # DB에 문자열로 저장

            flight_item = Flight(
                flight_name1,
                times_[0].text, times_[1].text,
                flight_name2,
                times_[2].text, times_[3].text,
                normalized_cost_str  # ex) "260309"
            )
            flight_list.append(flight_item)
            if num >= 50:
                break
            num += 1
        except Exception as e:
            print("항공권 정보 추출 실패:", e)
    
    driver.close()
    
    # 현재 시각(KST)
    kst = pytz.timezone("Asia/Seoul")
    now = datetime.now(kst)
    fetch_time = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # DB 연결: app.py와 동일한 DB를 사용 (경로: "db/flight_schedule.db")
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    DB_DIR = os.path.join(BASE_DIR, "db")
    DB_FILE = os.path.join(DB_DIR, "flight_schedule.db")
    conn = sqlite3.connect(DB_FILE)
    for flight in flight_list:
        conn.execute('''
            INSERT INTO flight_results (
                schedule_id,
                flight_name1, flight_time_s1, flight_time_e1,
                flight_name2, flight_time_s2, flight_time_e2,
                flight_cost, fetch_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            sched['id'],
            flight.flight_name1, flight.flight_time_s1, flight.flight_time_e1,
            flight.flight_name2, flight.flight_time_s2, flight.flight_time_e2,
            flight.flight_cost,  # 이미 쉼표 제거, 원 단위 정수 -> 문자열
            fetch_time
        ))
    conn.commit()
    conn.close()
    print(f"Schedule {sched['id']} 항공권 정보 저장 완료.")
