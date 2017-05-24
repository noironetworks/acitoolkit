import time
import acitoolkit

# create .crt and .key files with:
# openssl req -new -newkey rsa:1024 -days 36500 -nodes -x509 -keyout user.key -out user.crt -subj '/CN=User ABC/O=Cisco Systems/C=US'
# add the .crt file to APIC to the user you want to authenticate and give it a name

user = 'admin'
url_subs = '/api/mo/uni/tn-common.json?subscription=yes'
key = '/root/admin.key'
cert_name_on_apic = 'admin'
url_apic = 'https://172.28.184.30'

session = acitoolkit.Session(url_apic, user, cert_name=cert_name_on_apic, key=key)
session.login()
session.subscribe(url_subs)

while True:
    while session.has_events(url_subs):
        event = session.get_event(url_subs)['imdata'][0]
        print event
    time.sleep(1)
