import os, json, time, uuid, threading
from pathlib import Path
from datetime import datetime, timezone
import requests
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
BASE=Path(__file__).resolve().parent; load_dotenv(BASE/'.env')
HOST=os.getenv('MQTT_HOST','').strip(); URL=os.getenv('ELASTIC_URL','').strip().rstrip('/'); KEY=os.getenv('ELASTIC_API_KEY','').strip(); TOPIC=os.getenv('MQTT_TOPIC','ticket-demo/events')
CLIENT_ID=os.getenv('MQTT_WORKER_CLIENT_ID','ticket-indexer').strip() or 'ticket-indexer'
if not all([HOST,URL,KEY]): raise SystemExit('MQTT_HOST, ELASTIC_URL, ELASTIC_API_KEY 설정이 필요합니다.')
status={'mqtt':'연결 중','elastic':'확인 중','indexed':0,'last_error':'','subscribed':False,'client_id':CLIENT_ID}
def write_status():
 while True:
  status['heartbeat']=datetime.now(timezone.utc).isoformat()
  try: (BASE/'worker_status.json').write_text(json.dumps(status,ensure_ascii=False),encoding='utf-8')
  except OSError: pass
  time.sleep(2)
threading.Thread(target=write_status,daemon=True).start()
headers={'Authorization':'ApiKey '+KEY,'Content-Type':'application/json'}
http=requests.Session()
def connect(c,u,flags,reason,props):
 status['mqtt']='연결됨' if reason==0 else '연결 실패'
 if reason==0: c.subscribe('$share/ticket-indexers/'+TOPIC,qos=1)
def subscribed(c,u,mid,reasons,props): status['subscribed']=all(not x.is_failure for x in reasons)
def disconnect(c,u,flags,reason,props): status.update(mqtt='연결 끊김',subscribed=False)
def message(c,u,msg):
 try:
  item=json.loads(msg.payload); ident=str(uuid.UUID(item['event_id']))
  # Index by event ID: MQTT QoS 1 redelivery does not duplicate documents.
  while True:
   try:
    r=http.put(URL+'/ticket-events/_doc/'+ident,headers=headers,json=item,timeout=10)
    if r.ok:
     status.update(elastic='저장 성공',indexed=status['indexed']+1,last_error=''); c.ack(msg.mid,msg.qos); break
    status.update(elastic='저장 실패',last_error=f'HTTP {r.status_code}: {r.text[:180]}')
   except requests.RequestException as e: status.update(elastic='연결 실패',last_error=str(e)[:180])
   time.sleep(3)
 except (ValueError,KeyError,TypeError): status['last_error']='잘못된 이벤트 형식'; c.ack(msg.mid,msg.qos)
c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id=CLIENT_ID,clean_session=False,manual_ack=True); c.on_connect=connect; c.on_disconnect=disconnect; c.on_subscribe=subscribed; c.on_message=message
if os.getenv('MQTT_USERNAME'): c.username_pw_set(os.getenv('MQTT_USERNAME'),os.getenv('MQTT_PASSWORD',''))
if os.getenv('MQTT_TLS','true').lower()=='true': c.tls_set()
c.connect(HOST,int(os.getenv('MQTT_PORT','8883')),60); c.loop_forever(retry_first_connection=True)
