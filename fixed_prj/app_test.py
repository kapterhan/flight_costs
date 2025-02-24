from flask import Flask, request, render_template, redirect, url_for
import sqlite3
import os
import threading
import schedule
import time
import naver_flight_every_2hour  # 수정된 모듈 사용 (fetch_flight_info_for_schedule 함수 포함)
from selenium.webdriver.common.by import By  # 필요시 사용
import pandas as pd
from datetime import datetime, timedelta, time as dt_time
import pytz
from io import BytesIO
import base64
import matplotlib
matplotlib.use('Agg')  # GUI 백엔드 대신 Agg 사용
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
font_path = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
font_prop = fm.FontProperties(fname=font_path)
# 1) 폰트 지정
plt.rc('font', family=font_prop.get_name())  # 직접 폰트 적용
# 2) 유니코드에서 마이너스 기호가 깨지는 현상 방지
plt.rc('axes', unicode_minus=False)

app = Flask(__name__)

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

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            departure_date TEXT,
            return_date TEXT,
            departure TEXT,
            destination TEXT,
            adult_count INTEGER,
            child_count INTEGER,
            infant_count INTEGER,
            seat_type TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS flight_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            flight_name1 TEXT,
            flight_time_s1 TEXT,
            flight_time_e1 TEXT,
            flight_name2 TEXT,
            flight_time_s2 TEXT,
            flight_time_e2 TEXT,
            flight_cost TEXT,
            fetch_time TEXT,
            FOREIGN KEY(schedule_id) REFERENCES schedules(id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

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

def format_date(date_str):
    return date_str.replace('-', '')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/schedule')
def schedule_page():
    user_id = request.args.get('userId', '')
    return render_template('schedule.html', user_id=user_id)

@app.route('/create_schedule', methods=['POST'])
def create_schedule():
    user_id = request.form['userId']
    departure_date = format_date(request.form['departureDate'])
    return_date = format_date(request.form['returnDate'])
    departure = request.form['departure']
    destination = request.form['destination']
    adult_count = int(request.form['adultCount'])
    child_count = int(request.form['childCount'])
    infant_count = int(request.form['infantCount'])
    seat_type_key = request.form['seatType']
    seat_type = seat_type_mapping.get(seat_type_key, seat_type_key)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO schedules (
            user_id, departure_date, return_date, departure,
            destination, adult_count, child_count, infant_count, seat_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id, departure_date, return_date, departure, destination,
        adult_count, child_count, infant_count, seat_type
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('schedule_page', userId=user_id))

@app.route('/view_schedule')
def view_schedule():
    user_id = request.args.get('userId', '')
    conn = get_db_connection()
    schedule_rows = conn.execute(
        'SELECT * FROM schedules WHERE user_id = ?',
        (user_id,)
    ).fetchall()
    schedules = [dict(row) for row in schedule_rows]

    for sched in schedules:
        results = conn.execute('''
            SELECT *
            FROM flight_results
            WHERE schedule_id = ?
              AND fetch_time = (
                  SELECT MAX(fetch_time) FROM flight_results WHERE schedule_id = ?
              )
            ORDER BY CAST(REPLACE(flight_cost, "₩", "") AS INTEGER) ASC
            LIMIT 10
        ''', (sched['id'], sched['id'])).fetchall()
        flight_results = [dict(r) for r in results]

        # 변동률 계산
        for flight in flight_results:
            try:
                # flight['flight_cost'] -> 예: "1016794" (문자열) 이라고 가정
                current_price = int(flight['flight_cost'])  # 원 단위 정수
                current_time = datetime.strptime(flight['fetch_time'], "%Y-%m-%d %H:%M:%S")

                # 이전 한 시간 범위
                current_hour_block = current_time.replace(minute=0, second=0, microsecond=0)
                previous_hour_start = current_hour_block - timedelta(hours=1)
                previous_hour_end = previous_hour_start.replace(minute=59, second=59, microsecond=999999)

                conn2 = get_db_connection()
                row = conn2.execute('''
                    SELECT AVG(CAST(flight_cost AS INTEGER)) as avg_price
                    FROM flight_results
                    WHERE schedule_id = ?
                      AND flight_name1 = ?
                      AND flight_time_s1 = ?
                      AND flight_time_e1 = ?
                      AND flight_name2 = ?
                      AND flight_time_s2 = ?
                      AND flight_time_e2 = ?
                      AND fetch_time BETWEEN ? AND ?
                ''', (
                    sched['id'],
                    flight['flight_name1'].strip(),
                    flight['flight_time_s1'].strip(),
                    flight['flight_time_e1'].strip(),
                    flight['flight_name2'].strip(),
                    flight['flight_time_s2'].strip(),
                    flight['flight_time_e2'].strip(),
                    previous_hour_start.strftime("%Y-%m-%d %H:%M:%S"),
                    previous_hour_end.strftime("%Y-%m-%d %H:%M:%S")
                )).fetchone()
                conn2.close()

                if row and row['avg_price']:
                    # avg_price도 원 단위 정수(평균이므로 float지만 대략 xx.x)
                    avg_previous_hour = row['avg_price']  # 예: 293333.0
                    variation = (current_price - avg_previous_hour) / avg_previous_hour * 100
                    flight['variation'] = variation
                else:
                    flight['variation'] = None

                print("DEBUG:")
                print("  flight_name1:", flight['flight_name1'])
                print("  current_price:", current_price)
                print("  avg_previous_hour:", row['avg_price'] if row else None)
                print("  variation:", flight['variation'])
                print("========================================")

            except Exception as e:
                flight['variation'] = None
                print("Error calculating variation:", e)

        sched['flight_results'] = flight_results
        sched['seat_type'] = reverse_seat_type.get(sched['seat_type'], sched['seat_type'])
        sched['departure'] = code_to_city.get(sched['departure'], sched['departure'])
        sched['destination'] = code_to_city.get(sched['destination'], sched['destination'])

    conn.close()
    return render_template('view_schedule.html', schedules=schedules, user_id=user_id)


@app.route('/view_flight_trend')
def view_flight_trend():
    # 파라미터
    schedule_id = request.args.get('schedule_id')
    user_id = request.args.get('userId', '')
    flight_name1 = request.args.get('flight_name1', '').strip()
    flight_time_s1 = request.args.get('flight_time_s1', '').strip()
    flight_time_e1 = request.args.get('flight_time_e1', '').strip()
    flight_name2 = request.args.get('flight_name2', '').strip()
    flight_time_s2 = request.args.get('flight_time_s2', '').strip()
    flight_time_e2 = request.args.get('flight_time_e2', '').strip()

    conn = get_db_connection()
    rows = conn.execute('''
        SELECT flight_cost, fetch_time
        FROM flight_results
        WHERE schedule_id = ?
          AND flight_name1 = ?
          AND flight_time_s1 = ?
          AND flight_time_e1 = ?
          AND flight_name2 = ?
          AND flight_time_s2 = ?
          AND flight_time_e2 = ?
        ORDER BY fetch_time ASC
    ''', (
        schedule_id,
        flight_name1, flight_time_s1, flight_time_e1,
        flight_name2, flight_time_s2, flight_time_e2
    )).fetchall()
    conn.close()

    if not rows:
        return "해당 항공권의 데이터를 찾을 수 없습니다."

    # 시계열 구성
    from datetime import datetime
    times = []
    prices = []
    for row in rows:
        # flight_cost가 "1016794"처럼 원 단위 정수 문자열
        try:
            price = int(row['flight_cost'])
        except:
            continue
        try:
            t = datetime.strptime(row['fetch_time'], "%Y-%m-%d %H:%M:%S")
        except:
            continue
        times.append(t)
        prices.append(price)

    # 리샘플링 (5분 단위 mean) + ffill
    import pandas as pd
    df = pd.DataFrame({'time': times, 'price': prices})
    df['time'] = pd.to_datetime(df['time'])
    df.set_index('time', inplace=True)
    df_resampled = df.resample('5min').mean()
    df_resampled = df_resampled.ffill()

    resampled_times = df_resampled.index.to_pydatetime().tolist()
    resampled_prices = df_resampled['price'].tolist()

    # 그래프
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker

    plt.figure(figsize=(10, 5))
    # 원본 times, prices가 아니라 리샘플링된 resampled_times, resampled_prices 사용 가능
    plt.plot(resampled_times, resampled_prices, marker='o', linestyle='-', color='blue')
    plt.title("개별 항공권 가격 추이")
    plt.xlabel("시간")
    plt.ylabel("금액 (천원)")
    plt.grid(True)
    plt.gcf().autofmt_xdate()

    ax = plt.gca()
    # y축 눈금을 천원 단위로 표시
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x/1000)}"))

    # x축 라벨 간격(30분)
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    # x축 범위(최근 4시간)
    if resampled_times:
        end_time = max(resampled_times)
        start_time = end_time - timedelta(hours=4)
        plt.xlim(start_time, end_time)

    from io import BytesIO
    import base64
    buf = BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    buf.close()
    plt.close()

    return render_template(
        'view_single_flight_price_trend.html',
        image_base64=image_base64,
        user_id=user_id,
        schedule_id=schedule_id,
        flight_name1=flight_name1,
        flight_time_s1=flight_time_s1,
        flight_time_e1=flight_time_e1,
        flight_name2=flight_name2,
        flight_time_s2=flight_time_s2,
        flight_time_e2=flight_time_e2
    )

@app.route('/view_all_results')
def view_all_results():
    schedule_id = request.args.get('schedule_id')
    user_id = request.args.get('userId', '')
    conn = get_db_connection()

    sched_row = conn.execute(
        'SELECT * FROM schedules WHERE id = ?', (schedule_id,)
    ).fetchone()
    if not sched_row:
        conn.close()
        return "잘못된 일정 ID입니다."
    sched = dict(sched_row)

    departure_name = code_to_city.get(sched['departure'], sched['departure'])
    destination_name = code_to_city.get(sched['destination'], sched['destination'])

    results = conn.execute('''
        SELECT *
        FROM flight_results
        WHERE schedule_id = ?
          AND fetch_time = (
              SELECT MAX(fetch_time) FROM flight_results WHERE schedule_id = ?
          )
        ORDER BY CAST(flight_cost AS INTEGER) ASC
    ''', (schedule_id, schedule_id)).fetchall()
    results = [dict(r) for r in results]
    conn.close()

    return render_template(
        'view_all_results.html',
        results=results,
        schedule_id=schedule_id,
        user_id=user_id,
        departure_name=departure_name,
        destination_name=destination_name
    )

@app.route('/view_lowest_price_trend')
def view_lowest_price_trend():
    schedule_id = request.args.get('schedule_id')
    user_id = request.args.get('userId', '')
    conn = get_db_connection()

    query = '''
    SELECT fetch_time, flight_cost
    FROM flight_results
    WHERE schedule_id = ?
    ORDER BY fetch_time ASC
    '''
    rows = conn.execute(query, (schedule_id,)).fetchall()
    conn.close()

    if not rows:
        return "최저가 추이 데이터를 찾을 수 없습니다."

    from collections import defaultdict
    groups = defaultdict(list)
    for row in rows:
        ft = row["fetch_time"]
        try:
            price = int(row["flight_cost"])  # 원 단위
        except:
            continue
        groups[ft].append(price)

    times = []
    min_prices = []
    avg_lowest_20 = []

    for ft in sorted(groups.keys()):
        try:
            t = datetime.strptime(ft, "%Y-%m-%d %H:%M:%S")
        except:
            continue
        prices = sorted(groups[ft])
        if not prices:
            continue
        min_price = prices[0]
        subset = prices[:20]
        avg_price = sum(subset) / len(subset)
        times.append(t)
        min_prices.append(min_price)
        avg_lowest_20.append(avg_price)

    # Pandas 리샘플링
    df = pd.DataFrame({
        'time': times,
        'min_price': min_prices,
        'avg_price': avg_lowest_20
    })
    df['time'] = pd.to_datetime(df['time'])
    df.set_index('time', inplace=True)

    df_resampled = df.resample('5min').mean().ffill()

    resampled_times = df_resampled.index.to_pydatetime().tolist()
    resampled_min_prices = df_resampled['min_price'].tolist()
    resampled_avg_prices = df_resampled['avg_price'].tolist()

    plt.figure(figsize=(10,5))
    plt.plot(resampled_times, resampled_min_prices, marker='o', linestyle='-', color='blue', label='최저가')
    plt.plot(resampled_times, resampled_avg_prices, marker='s', linestyle='--', color='red', label='하위 20개 평균')
    plt.xlabel("시간")
    plt.ylabel("금액 (천원)")
    plt.legend()
    plt.grid(True)
    plt.gcf().autofmt_xdate()

    ax = plt.gca()
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{int(x/1000)}"))

    if resampled_times:
        current_time = datetime.now()
        start_time = current_time - timedelta(hours=4)
        end_time = current_time
        plt.xlim(start_time, end_time)

    buf = BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    image_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    buf.close()
    plt.close()

    return render_template(
        "view_lowest_price_trend.html",
        image_base64=image_base64,
        user_id=user_id,
        schedule_id=schedule_id
    )

@app.route('/delete_schedule')
def delete_schedule():
    schedule_id = request.args.get('id')
    user_id = request.args.get('userId', '')
    if schedule_id:
        conn = get_db_connection()
        conn.execute('DELETE FROM schedules WHERE id = ?', (schedule_id,))
        conn.commit()
        conn.close()
    return redirect(url_for('view_schedule', userId=user_id))

def fetch_all_schedules_flight_info():
    conn = get_db_connection()
    schedule_rows = conn.execute('SELECT * FROM schedules').fetchall()
    conn.close()
    schedules = [dict(row) for row in schedule_rows]
    for sched in schedules:
        try:
            naver_flight_every_2hour.fetch_flight_info_for_schedule(sched)
        except Exception as e:
            print(f"스케줄 {sched['id']} 항공권 정보 가져오기 실패:", e)

schedule.every(2).minutes.do(fetch_all_schedules_flight_info)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=run_scheduler, daemon=True).start()

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)
