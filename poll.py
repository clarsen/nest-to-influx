import nest
import sys
import time
import traceback
import yaml
import datetime
import arrow
from dateutil import tz

import requests

HEALTHCHECK_ADJUST_TEMPERATURE_URL="https://hchk.io/<your_healthcheck_id>"
HEALTHCHECK_NEST_TO_INFLUX_URL="https://hchk.io/<your_healthcheck_id>"

from influxdb import InfluxDBClient


def parse_sched():
    with open("schedule.yaml") as f:
        sched = yaml.load(f)
    #print(sched)
    events = []
    for status in ['home', 'away']:
        for event in sched[status]['dates']:
            dt = arrow.get("%s %s" % (event, sched[status]['time']),'M/D/YYYY HH:mm', tzinfo=tz.gettz('US/Pacific')) 
            print(event, dt) 
            events.append((dt,status, sched[status]['target_temperature_low'], sched[status]['target_temperature_high']))

    #print(events)
    def ts_for_tuple(x):
        return x[0]
    events = sorted(events, key=ts_for_tuple)
    print(events)
    return events
    # check whether current day is in range

def status(events, dt):
    for idx in range(len(events)):
        if events[idx][0] <= dt and dt <= events[idx+1][0]:
            print(events[idx])
            return events[idx]
    raise Exception("no info")


client = InfluxDBClient(host="localhost", port=8086, database="ruuvi")

client_id = '<your_nest_product_id>'
client_secret = '<your_nest_product_secret>'
access_token_cache_file = 'nest.json'
napi = nest.Nest(client_id=client_id, client_secret=client_secret, access_token_cache_file=access_token_cache_file)

if napi.authorization_required:
    print('Go to ' + napi.authorize_url + ' to authorize, then enter PIN below')
    if sys.version_info[0] < 3:
        pin = raw_input("PIN: ")
    else:
        pin = input("PIN: ")
    napi.request_token(pin)


cur_hvac_state = None
def emit_hvac_state_transition(device):
    global cur_hvac_state
    ret = {
	"measurement": "nest.hvac.status",
	"tags": {
	    "device": device.name,
	},
	"fields": {
	    "value": device.hvac_state,
	}
    }
    if cur_hvac_state is None:
        cur_hvac_state = device.hvac_state
        return ret
    elif cur_hvac_state != device.hvac_state:
        cur_hvac_state = device.hvac_state
        return ret
    else:
        return {}

while True:
    for structure in napi.structures:
        for device in structure.thermostats:
            print ('        Device: %s' % device.name)
            print ('        Where: %s' % device.where)
            print ('            Mode       : %s' % device.mode)
            print ('            HVAC State : %s' % device.hvac_state)
            print ('            Fan        : %s' % device.fan)
            print ('            Fan Timer  : %i' % device.fan_timer)
            print ('            Temp       : %0.1fC' % device.temperature)
            print ('            Humidity   : %0.1f%%' % device.humidity)
            #print ('            Target     : %0.1fC' % device.target)
            print ('            Target     : ', device.target)
            print ('            Eco High   : %0.1fC' % device.eco_temperature.high)
            print ('            Eco Low    : %0.1fC' % device.eco_temperature.low)

            print ('            hvac_emer_heat_state  : %s' % device.is_using_emergency_heat)

            print ('            online                : %s' % device.online)

            json_body = []
            hvac_state_rec = emit_hvac_state_transition(device)
            if hvac_state_rec:
                json_body.append(hvac_state_rec)
            json_body.append({
                "measurement": "nest.temp_f",
                "tags": {
                    "device": device.name,
                },
                "fields": {
                    "value": device.temperature,
                }
            })
            json_body.append({
                "measurement": "nest.humidity",
                "tags": {
                    "device": device.name,
                },
                "fields": {
                    "value": device.humidity,
                }
            })
            try:
                events = parse_sched()
                target_state = status(events, arrow.utcnow())
                if device.target.low != target_state[2] or device.target.high != target_state[3]:
                    print("setting temp to %d,%d" % (target_state[2], target_state[3]))
                    device.target = (target_state[2], target_state[3])
                json_body.append({
                    "measurement": "nest.target_temperature_low",
                    "tags": {
                        "device": device.name,
                    },
                    "fields": {
                        "value": target_state[2],
                    }
                })
                json_body.append({
                    "measurement": "nest.target_temperature_high",
                    "tags": {
                        "device": device.name,
                    },
                    "fields": {
                        "value": target_state[3],
                    }
                })
                requests.get(HEALTHCHECK_ADJUST_TEMPERATURE_URL)
            except:
                traceback.print_exc()
            #import sys
            #sys.exit(0)
            print("would send",json_body)
            print("device", device)
            client.write_points(json_body)
    try:
        requests.get(HEALTHCHECK_NEST_TO_INFLUX_URL)
    except:
        pass
    time.sleep(120)
