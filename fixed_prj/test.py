from flask import Flask, request, render_template, redirect, url_for
import sqlite3
import os
import threading
import time
import schedule
import naver_flight_every_2hour  # 수정된 모듈 사용 (fetch_flight_info_for_schedule 함수 포함)
from selenium.webdriver.common.by import By  # 필요시 사용
import pandas as pd
from datetime import datetime
import pytz
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')  # GUI 백엔드 대신 Agg 사용
import matplotlib.pyplot as plt
from datetime import datetime
import matplotlib.ticker as ticker
import base64
# 좌석 타입 매핑 및 역매핑
seat_type_mapping = {
    'economy': 'y',
    'premiumEconomy': 'p',
    'business': 'c',
    'first': 'f'
}
reverse_seat_type = {
    'y': '일반석',
    'p': '프리미엄 일반석',
    'c': '비즈니스석',
    'f': '일등석'
}
# 도시 코드 역매핑
code_to_city = {
    'SEL': '서울',
    'ICN': '인천',
    'GMP': '김포',
    'PUS': '부산',
    'CJU': '제주',
    'TYO': '도쿄',
    'OSA': '오사카',
    'FUK': '후쿠오카',
    'SPK': '삿포로',
    'OKA': '오키나와',
    'NHA': '나트랑',
    'DAD': '다낭',
    'BKK': '방콕',
    'MNL': '마닐라',
    'CEB': '세부',
    'DPS': '발리',
    'PAR': '파리',
    'LON': '런던',
    'ROM': '로마',
    'BCN': '바르셀로나',
    'ZRH': '취리히',
    'FRA': '프랑크푸르트',
    'IST': '이스탄불',
    'TPE': '타이베이',
    'HFG': '홍콩',
    'MFM': '마카오',
    'PVG': '상하이',
    'UBN': '울란바토르',
    'LAX': 'LA',
    'HNL': '하와이',
    'NYC': '뉴욕',
    'YVR': '밴쿠버',
    'GUM': '괌',
    'SPN': '사이판',
    'SYD': '시드니'
}

# DB 파일 경로 (웹 일정 저장용)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_DIR = os.path.join(BASE_DIR, "db")
if not os.path.exists(DB_DIR):
    os.makedirs(DB_DIR)
DB_FILE = os.path.join(DB_DIR, "flight_schedule.db")

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

conn = get_db_connection()
schedule_rows = conn.execute('SELECT * FROM schedules WHERE user_id = ?', ("이한희",)).fetchall()
schedules = [dict(row) for row in schedule_rows]

print("이전:",schedules)
print()

for sched in schedules:
    # 최신 fetch_time을 기준으로 10개만 가져오도록 쿼리 수정
    results = conn.execute(
        '''
        SELECT * FROM flight_results 
        WHERE schedule_id = ? 
            AND fetch_time = (
                SELECT MAX(fetch_time) FROM flight_results WHERE schedule_id = ?
            )
        ORDER BY CAST(REPLACE(flight_cost, "₩", "") AS INTEGER) ASC
        LIMIT 10
        ''',
        (sched['id'], sched['id'])
    ).fetchall()
    sched['flight_results'] = [dict(r) for r in results]
    sched['seat_type'] = reverse_seat_type.get(sched['seat_type'], sched['seat_type'])
    sched['departure'] = code_to_city.get(sched['departure'], sched['departure'])
    sched['destination'] = code_to_city.get(sched['destination'], sched['destination'])
conn.close()

print("이후후:",schedules)