# KOPO 티켓 예매 행동 분석

가상 티켓 예매 과정에서 인간과 자동화 시나리오의 행동을 기록하고 비교하는 교육용 프로젝트입니다. 보안문자 입력, 좌석 선택 시 마우스 이동, 주문 정보 입력을 살펴보고, 수집한 로그를 Elastic과 Kibana에서 확인합니다.

## 참고 자료

- [시스템 동작 설명 PDF](docs/system-guide.pdf): 행동 수집부터 로그 전송·저장·조회까지의 흐름
- [시연 영상](docs/demo.mp4): 프로젝트 화면과 동작 예시 (약 75 MB, 다운로드 후 재생 가능)

## 동작 흐름

```text
브라우저 행동 → Flask / Python 분석 → SQLite
                                      ↓ MQTT
                                    EMQX
                                      ↓ 구독 워커
                               Elasticsearch → Kibana
```

브라우저가 입력 시간과 마우스 좌표 등을 서버에 전송합니다. 서버는 측정 결과와 이벤트를 로컬 SQLite에 기록합니다. 클라우드를 설정하면 MQTT로 EMQX에 전달하고, 구독 워커가 Elasticsearch에 저장합니다. Kibana의 Discover와 Dashboard에서 로그를 조회할 수 있습니다. MQTT 브로커의 수신 확인과 Elasticsearch 저장 성공은 별개의 단계입니다.

## 실행 방법 (Windows)

Python 3.10 이상이 필요합니다. 프로젝트 폴더에서 PowerShell을 열고 실행합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

브라우저에서 [예매 연습 화면](http://127.0.0.1:5050/practice/intro)을 열고 인간 예매 또는 AI 예매를 선택합니다. [발표 화면](http://127.0.0.1:5050/presentation)에서는 보안문자, 마우스 경로, 주문·결제 시나리오를 볼 수 있습니다. [탐지 관제](http://127.0.0.1:5050/)에서는 이벤트와 탐지 근거를 확인합니다. 종료하려면 서버 창에서 `Ctrl+C`를 누르세요.

클라우드 설정 없이도 로컬 시연과 기록을 사용할 수 있습니다. Elasticsearch와 Kibana 연동을 사용하려면 다음을 추가로 설정하세요.

1. `.env.example`을 `.env`로 복사하고 EMQX 접속 정보, Elasticsearch URL과 API 키를 입력합니다. Kibana URL은 필요에 따라 설정합니다.
2. 별도의 PowerShell 창에서 `.\.venv\Scripts\python.exe worker.py`를 실행한 뒤 웹 서버를 실행합니다.
3. Kibana에서 `ticket-events` 데이터 뷰를 만들고 시간 필드로 `@timestamp`를 선택합니다. Discover에서 이벤트를 확인하거나 Dashboard를 구성합니다.

`.env`, SQLite 기록과 로그 파일은 Git에 포함하지 않습니다. 접속 정보는 본인의 환경에서만 설정하세요.

## 구성

- `app.py`, `practice.py`: Flask 서버와 가상 예매 흐름
- `captcha_timing.py`, `interaction_metrics.py`, `checkout.py`: 단계별 행동 측정
- `behavior.py`, `detector.py`: 행동 신호와 규칙 기반 판정
- `worker.py`: MQTT 구독 및 Elasticsearch 저장
- `templates/`, `static/`: 화면과 브라우저 코드
- `tests/`: 주요 시나리오 검증 코드

## 해석할 때

AI 예매는 이 로컬 실험을 위한 자동화·재현 시나리오를 포함합니다. 탐지 점수는 관찰된 행동에 대한 규칙 기반 신호이며 사람 또는 AI를 확정하는 판정이나 실제 서비스 정확도가 아닙니다. 실제 티켓 사이트에 접속하거나 실제 결제를 처리하지 않는 교육용 모형입니다.
