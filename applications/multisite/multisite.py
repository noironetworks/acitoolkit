from acitoolkit.acitoolkit import *
import json
import re
import threading


def strip_illegal_characters(name):
    chars_all_good = True
    for character in name:
        if character.isalnum() or character in ('_', '.', ':', '-'):
            continue
        chars_all_good = False
        name = name.replace(character, '')
    if chars_all_good:
        return name
    return strip_illegal_characters(name)


class MultisiteTag(object):
    def __init__(self, contract_name, export_state, remote_site):
        # Remove the local site from the contract if present
        if ':' in contract_name:
            names = contract_name.split(':')
            assert len(names) == 2
            contract_name = names[1]
        self._contract_name = contract_name
        self._export_state = export_state
        self._remote_site = remote_site

    @staticmethod
    def is_multisite_tag(tag):
        return re.match(r'multisite:.*:contract:.*:site:.*', tag)

    @classmethod
    def fromstring(cls, tag):
        if not cls.is_multisite_tag(tag):
            assert cls.is_multisite_tag(tag)
            return None
        tag_data = tag.split(':')
        export_state = tag_data[1]
        contract_name = tag_data[3]
        remote_site_name = tag_data[5]
        new_tag = cls(contract_name, export_state, remote_site_name)
        return new_tag

    def __str__(self):
        return 'multisite:' + self._export_state + ':contract:' + self._contract_name + ':site:' + self._remote_site

    def is_imported(self):
        if self._export_state == 'imported':
            return True
        return False

    def get_local_contract_name(self):
        if self.is_imported():
            local_contract_name = strip_illegal_characters(self._remote_site) + ':' + self._contract_name
            return local_contract_name
        return self._contract_name


    def get_contract_name(self):
        return self._contract_name

    def get_remote_site_name(self):
        return self._remote_site

    def get_export_state(self):
        return self._export_state

    # def set_remote_site_name(self, site_name):
    #     self._remote_site = site_name


class MultisiteMonitor(threading.Thread):
    """
    Monitor thread responsible for subscribing for local Endpoints and EPG notifications.
    """
    def __init__(self, session, local_site):
        threading.Thread.__init__(self)
        self._session = session
        self._local_site = local_site
        self._exit = False
        self.remote_sites = []

    def exit(self):
        """
        Indicate that the thread should exit.
        """
        self._exit = True


    def handle_contract_relation_event(self, event, provides=True):
        if provides:
            apic_class = 'fvRsProv'
            apic_dn_class = 'rsprov'
        else:
            apic_class = 'fvRsCons'
            apic_dn_class = 'rscons'

        event_attributes = event['imdata'][0][apic_class]['attributes']
        if 'status' in event_attributes:
            status = event_attributes['status']
        else:
            status = 'created'
        dn = event_attributes['dn']
        tenant_name = str(dn.split('uni/tn-')[1].split('/')[0])
        contract_name = str(dn.split('/%s-' % apic_dn_class)[1])
        cdb_entry = self._local_site.contract_db.find_entry(tenant_name, contract_name)
        app_name = str(dn.split('/ap-')[1].split('/')[0])
        epg_name = str(dn.split('/epg-')[1].split('/')[0])
        if provides and (cdb_entry is None or not cdb_entry.is_exported()):
            # TODO handle imported contracts here - these are contracts that have been imported at runtime

            # Ignore this event
            return
        elif not provides and (cdb_entry is None or cdb_entry.is_exported()):
            # Ignore this event
            return
        # Need to export this EPG
        export_tenant = Tenant(tenant_name)
        export_app = AppProfile(app_name, export_tenant)
        export_epg = EPG(epg_name, export_app)
        if status == 'deleted':
            # If this is the last contract that this EPG is providing, delete the EPG
            if len(self._local_site.epg_db.find_entries(tenant_name, app_name, epg_name)) == 1:
                export_epg.mark_as_deleted()
        export_contract = Contract(contract_name, export_tenant)
        if provides:
            export_epg.provide(export_contract)
            if status == 'deleted':
                export_epg.dont_provide(export_contract)
        else:
            export_epg.consume(export_contract)
            if status == 'deleted':
                export_epg.dont_consume(export_contract)
        tenant_json = export_tenant.get_json()
        for remote_site in cdb_entry.remote_sites:
            print 'Exporting EPG to remote site', remote_site
            site_obj = self._local_site.my_collector.get_site(remote_site)
            if site_obj is None:
                return
            self._local_site.contract_collector.export_epg(tenant_json,
                                                           contract_name,
                                                           site_obj)


    def handle_provided_contract_event(self, event):
        print 'handle_provided_contract_event'
        return self.handle_contract_relation_event(event, True)


    def handle_consumed_contract_event(self, event):
        print 'handle_consumed_contract_event'
        return self.handle_contract_relation_event(event, False)

    def run(self):
        # Subscribe to endpoints
        Endpoint.subscribe(self._session)

        # Subscribe to fvRsProv (EPGs providing Contracts)
        provides_url = '/api/class/fvRsProv.json?subscription=yes'
        resp = self._session.subscribe(provides_url)
        print 'response is', resp

        # Subscribe to fvRsCons (EPGs consuming Contracts)
        consumes_url = '/api/class/fvRsCons.json?subscription=yes'
        print 'response is', self._session.subscribe(provides_url)

        while not self._exit:
            if self._session.has_events(provides_url):
                self.handle_provided_contract_event(self._session.get_event(provides_url))

            if self._session.has_events(consumes_url):
                self.handle_provided_contract_event(self._session.get_event(consumes_url))

            if Endpoint.has_events(self._session):
                print 'Endpoint Event received'
                ep = Endpoint.get_event(self._session)
                epg = ep.get_parent()
                app = epg.get_parent()
                tenant = app.get_parent()
                if self._local_site.exports_epg(epg):

                    # TODO clean up this section and also handle ep.is_deleted() == True


                    tenant = Tenant('site2')
                    outside = OutsideEPG('site2-l3out', tenant)
                    tenant = Tenant('site2')
                    outside = OutsideEPG('site2-l3out', tenant)
                    l3if1 = L3Interface('l3if1')
                    l3if1.networks.append(ep.ip)
                    l3if1.set_l3if_type('ext-svi')
                    outside.attach(l3if1)
                    for contract_db_entry in self._local_site.get_all_provided_contracts(epg):
                        contract = Contract(contract_db_entry.contract_name, tenant)
                        outside.provide(contract)
                    phyif = Interface('eth', '1', '102', '1', '25')
                    l2if = L2Interface('eth 1/102/1/25', 'vlan', '500')
                    l2if.attach(phyif)
                    l3if1.attach(l2if)
                    #for remote_site in self.remote_sites:
                        #resp = tenant.push_to_apic(remote_site.session)
                        #if not resp.ok:
                        #    print "couldn't export", resp, resp.text
                    print '*****CONFIG FOR ENDPOINT*****'
                    print json.dumps(tenant.get_json(), indent=4, separators=(',', ':'))
                    print 'Exported endpoint'



class ContractCollector(object):
    """
    Class to collect the Contract from the APIC, along with all of the providing EPGs
    """
    classes_to_rename = {'fvAEPg': 'name',
                         'fvRsProv': 'tnVzBrCPName',
                         'fvRsProtBy': 'tnVzTabooName',
                         'vzBrCP': 'name',
                         'vzTaboo': 'name',
                         'vzFilter': 'name',
                         'vzRsSubjFiltAtt': 'tnVzFilterName',
                         'vzRsDenyRule': 'tnVzFilterName'}

    classes_to_tag = ['fvAEPg', 'fvTenant']

    def __init__(self, session, local_site_name):
        self._session = session
        self.local_site_name = local_site_name

    def _strip_dn(self, data):
        """
        Recursively remove dn attributes from the JSON data

        :param data: JSON dictionary
        :return: None
        """
        if isinstance(data, list):
            for item in data:
                self._strip_dn(item)
        else:
            for key in data:
                if 'dn' in data[key]['attributes']:
                    del data[key]['attributes']['dn']
                if 'children' in data[key]:
                    self._strip_dn(data[key]['children'])

    def _find_all_of_attribute(self, data, attribute, class_names):
        """
        Find all of the object instance names belonging to a set of APIC classes

        :param data: JSON dictionary
        :param class_names: list of strings containing APIC class names
        :return: list of tuples in the form of (classname, objectname)
        """
        resp = []
        if isinstance(data, list):
            for item in data:
                resp = resp + self._find_all_of_attribute(item, attribute, class_names)
            return resp
        for key in data:
            if key in class_names:
                resp.append((key, data[key]['attributes'][attribute]))
            if 'children' in data[key]:
                resp = resp + self._find_all_of_attribute(data[key]['children'], attribute, class_names)
        return resp

    def get_contract_config(self, tenant, contract):
        # Create the tenant configuration
        tenant = Tenant(tenant)
        tenant_json = tenant.get_json()

        # Grab the Contract
        contract_children_to_migrate = ['vzSubj', 'vzRsSubjFiltAtt' ]
        query_url = '/api/mo/uni/tn-%s/brc-%s.json?query-target=self&rsp-subtree=full' % (tenant, contract)
        for child_class in contract_children_to_migrate:
            query_url += '&rsp-subtree-class=%s' % child_class
        query_url += '&rsp-prop-include=config-only'

        ret = self._session.get(query_url)
        contract_json = ret.json()['imdata'][0]
        tenant_json['fvTenant']['children'].append(contract_json)

        # Get the Filters referenced by the Contract
        class_names = ['vzRsSubjFiltAtt']
        filters = self._find_all_of_attribute(tenant_json, 'tnVzFilterName', class_names)
        for (class_name, filter_name) in filters:
            query_url = ('/api/mo/uni/tn-%s/flt-%s.json?query-target=self&rsp-subtree=full'
                         '&rsp-prop-include=config-only' % (tenant.name, filter_name))
            ret = self._session.get(query_url)
            filter_json = ret.json()['imdata']
            if len(filter_json):
                tenant_json['fvTenant']['children'].append(filter_json[0])

        # Get the EPGs providing the contract
        query_url = '/api/mo/uni/tn-%s/brc-%s.json?query-target=subtree&target-subtree-class=vzRtProv' % (tenant.name, contract)
        ret = self._session.get(query_url)
        epgs = ret.json()['imdata']
        epg_children_to_collect = ['fvRsProv', 'tagInst', 'fvRsProtBy' ]
        url_extension = '.json?query-target=self&rsp-subtree=full&rsp-prop-include=config-only'
        for child_class in epg_children_to_collect:
            url_extension += '&rsp-subtree-class=%s' % child_class
        for epg in epgs:
            query_url = '/api/mo/' + epg['vzRtProv']['attributes']['tDn'] + url_extension
            epg_json = self._session.get(query_url).json()['imdata']
            app_name = epg_json[0]['fvAEPg']['attributes']['dn'].split('tn-%s/ap-' % tenant.name)[1]
            app_name = str(app_name.split('/')[0])
            existing_apps = tenant.get_children(AppProfile)
            app_already_exists = False
            for existing_app in existing_apps:
                if existing_app.name == app_name:
                    app_already_exists = True
            if not app_already_exists:
                app = AppProfile(app_name, tenant)
                tenant_json['fvTenant']['children'].append(app.get_json())
            for child in tenant_json['fvTenant']['children']:
                if 'fvAp' in child:
                    if child['fvAp']['attributes']['name'] == app_name:
                        assert 'children' in child['fvAp']
                        child['fvAp']['children'].append(epg_json)
        self._strip_dn(tenant_json)
        return tenant_json

    @staticmethod
    def _pprint_json(data):
        print json.dumps(data, indent=4, separators=(',', ':'))

    def get_imported_contracts(self):
        pass

    def get_exported_contracts(self):
        pass

    def _rename_classes(self, data):
        if isinstance(data, list):
            for item in data:
                self._rename_classes(item)
        else:
            for key in data:
                if key in ContractCollector.classes_to_rename:
                    local_name = data[key]['attributes'][ContractCollector.classes_to_rename[key]]
                    data[key]['attributes'][ContractCollector.classes_to_rename[key]] = strip_illegal_characters(self.local_site_name) + ':' + local_name
                if 'children' in data[key]:
                    self._rename_classes(data[key]['children'])

    def _get_tag(self, contract_name, site_name, exported=True):
        if exported:
            export_state = 'exported'
        else:
            export_state = 'imported'
        tag = 'multisite:%s:contract:' % export_state + contract_name + ':site:' + site_name
        return tag

    def get_local_tag(self, contract_name, site_name):
        return self._get_tag(contract_name, site_name, exported=True)

    def get_remote_tag(self, contract_name, site_name):
        return self._get_tag(contract_name, site_name, exported=False)

    def _tag_local_config(self, data, contract_name):
        tag = {'tagInst': {'attributes': {'name': self.get_local_tag(contract_name, self.local_site_name)}}}
        data['fvTenant']['fvAEPg']['children'].append(tag)


    def _tag_remote_config(self, data, contract_name):
        if isinstance(data, list):
            for item in data:
                self._tag_remote_config(item, contract_name)
        else:
            for key in data:
                if key in ContractCollector.classes_to_tag:
                    assert 'children' in data[key]
                    tag = {'tagInst': {'attributes': {'name': self.get_remote_tag(contract_name, self.local_site_name)}}}
                    data[key]['children'].append(tag)
                if 'children' in data[key]:
                    self._tag_remote_config(data[key]['children'],
                                            contract_name)

    def export_epg(self, tenant_json, contract_name, remote_site):
        print '***export_providing_epg***'
        self.export_contract_config(tenant_json, contract_name, remote_site)

    def export_contract_config(self, tenant_json, contract_name, remote_site):
        assert remote_site is not None
        print '*****export_contract_config*****', contract_name
        self._rename_classes(tenant_json)
        #tenant_json['fvTenant']['attributes']['name'] = 'site2' # TODO hard code the tenant name right now to make up for bad config
        self._tag_remote_config(tenant_json, contract_name)
        resp = remote_site.session.push_to_apic(Tenant.get_url(), tenant_json)
        if not resp.ok:
            print resp, resp.text
            print remote_site.name
            print Tenant.get_url()
            print tenant_json
            print '%% Could not export to remote APIC'
        return resp

class SiteLoginCredentials(object):
    def __init__(self, ip_address, user_name, password, use_https):
        self.ip_address = ip_address
        self.user_name = user_name
        self.password = password
        self.use_https = use_https

class Site(object):
    def __init__(self, name, credentials, local=False):
        self.name = name
        self.local = local
        self.credentials = credentials
        self.session = None
        self.logged_in = False

    def get_credentials(self):
        return self.credentials

    def login(self):
        url = self.credentials.ip_address
        if self.credentials.use_https:
            url = 'https://' + url
        else:
            url = 'http://' + url
        self.session = Session(url, self.credentials.user_name, self.credentials.password)
        resp = self.session.login()
        return resp

    def __eq__(self, other):
        if self.name == other.name:
            return True
        else:
            return False

    def shutdown(self):
        pass

    def start(self):
        resp = self.login()
        if not resp.ok:
            print('%% Could not login to APIC on Site', self.name)
        else:
            print('%% Logged into Site', self.name)
            self.logged_in = True
        print 'MICHSMIT STARTING SITE', self.name
        return resp

class ContractDBEntry(object):
    def __init__(self):
        self.tenant_name = None
        self.contract_name = None
        self.export_state = None
        self.remote_sites = []

    @classmethod
    def from_multisite_tag(cls, tenant_name, mtag):
        db_entry = cls()
        db_entry.tenant_name = tenant_name
        db_entry.contract_name = mtag.get_local_contract_name()
        db_entry.export_state = mtag.get_export_state()
        db_entry.remote_sites.append(mtag.get_remote_site_name())
        return db_entry

    def is_local(self):
        return self.export_state == 'local'

    def is_exported(self):
        return self.export_state == 'exported'

    def is_imported(self):
        return self.export_state == 'imported'

    def __eq__(self, other):
        if self.tenant_name == other.tenant_name and self.contract_name == other.contract_name:
            return True
        else:
            return False

    def add_remote_site(self, mtag):
        self.export_state = mtag.get_export_state()
        remote_site = mtag.get_remote_site_name()
        if remote_site not in self.remote_sites:
            self.remote_sites.append(remote_site)

    def get_remote_sites_as_string(self):
        resp = ''
        for remote_site in self.remote_sites:
            resp += remote_site + ', '
        return resp[:-2]

class ContractDB(object):
    def __init__(self):
        self._db = []

    def find_entry(self, tenant_name, contract_name):
        search_entry = ContractDBEntry()
        search_entry.tenant_name = tenant_name
        search_entry.contract_name = contract_name
        for entry in self._db:
            if entry == search_entry:
                return entry
        return None

    def has_entry(self, tenant_name, contract_name):
        if self.find_entry(tenant_name, contract_name) is not None:
            return True
        return False

    def find_all(self):
        return self._db

    def add_entry(self, entry):
        self._db.append(entry)

    def add_remote_site(self, tenant_name, mtag):
        entry = self.find_entry(tenant_name, mtag.get_local_contract_name())
        if entry is None:
            print 'No contract found for ', tenant_name, mtag.get_local_contract_name()
            assert False
        entry.add_remote_site(mtag)


class EpgDBEntry(object):
    def __init__(self):
        self.tenant_name = None
        self.app_name = None
        self.epg_name = None
        self.contract_name = None

class EpgDB(object):
    def __init__(self):
        self._db = []

    def add_entry(self, entry):
        self._db.append(entry)

    def find_entries(self, tenant_name, app_name, epg_name):
        resp = []
        for entry in self._db:
            if entry.tenant_name == tenant_name and entry.app_name == app_name and entry.epg_name == epg_name:
                resp.append(entry)
        return resp

    def find_epgs_using_contract(self, tenant_name, contract_name):
        resp = []
        for db_entry in self._db:
            if db_entry.contract_name == contract_name and db_entry.tenant_name == tenant_name:
                resp.append(db_entry)
        return resp

    def find_all(self):
        return self._db

    def print_db(self):
        print 'EPG Database'
        for entry in self._db:
            print 'tenant:', entry.tenant_name, 'app:', entry.app_name, 'epg:', entry.epg_name, 'contract:', entry.contract_name

class LocalSite(Site):
    def __init__(self, name, credentials, parent):
        super(LocalSite, self).__init__(name, credentials, local=True)
        self.contract_collector = None
        self.my_collector = parent
        self.monitor = None
        self.contract_db = ContractDB()
        self.epg_db = EpgDB()

    def start(self):
        resp = super(LocalSite, self).start()
        if resp.ok:
            self.contract_collector = ContractCollector(self.session, self.name)
            self.monitor = MultisiteMonitor(self.session, self)
            self.monitor.daemon = True
            self.monitor.start()
        return resp

    # def is_multisite_tag(self, tag):
    #     return re.match(r'multisite:.*:contract:.*:site:.*', tag)
    #
    # def is_imported_tag(self, tag):
    #     if self.is_multisite_tag(tag):
    #         data = tag.split(':')
    #         export_state = data[1]
    #         if export_state == 'imported':
    #             return True
    #     return False
    #
    # def get_contract_name_from_tag(self, tag):
    #     if not self.is_multisite_tag(tag):
    #         return None
    #     tag_data = tag.split(':')
    #     contract_name = tag_data[3]
    #     return contract_name
    #
    # def get_site_name_from_tag(self, tag):
    #     if not self.is_multisite_tag(tag):
    #         return None
    #     tag_data = tag.split(':')
    #     remote_site_name = tag_data[5]
    #     return remote_site_name

    def _populate_contracts_from_apic(self):
        resp = []
        tenants = Tenant.get_deep(self.session, limit_to=['vzBrCP', 'fvTenant', 'tagInst'])

        # First handle imported and exported contracts through the tags
        for tenant in tenants:
            if tenant.has_tags():
                tags = tenant.get_tags()
                for tag in tags:
                    if MultisiteTag.is_multisite_tag(tag):
                        mtag = MultisiteTag.fromstring(tag)
                        db_entry = self.contract_db.find_entry(tenant.name, mtag.get_local_contract_name())
                        if db_entry is None:
                            db_entry = ContractDBEntry.from_multisite_tag(tenant.name, mtag)
                            self.contract_db.add_entry(db_entry)
                        else:
                            self.contract_db.add_remote_site(tenant.name, mtag)

        # Next, handle the non-exported local contracts
        for tenant in tenants:
            contracts = tenant.get_children(Contract)
            for contract in contracts:
                db_entry = self.contract_db.find_entry(tenant.name, contract.name)
                if db_entry is None:
                    db_entry = ContractDBEntry()
                    db_entry.tenant_name = tenant.name
                    db_entry.contract_name = contract.name
                    db_entry.export_state = 'local'
                    self.contract_db.add_entry(db_entry)

        # Sanity check : This can be removed later
        contract_count = 0
        print 'FROM CONTRACTS'
        for tenant in tenants:
            contracts = tenant.get_children(Contract)
            for contract in contracts:
                print 'tenant:', tenant.name, 'contract:', contract.name
                contract_count += 1
        print 'FROM DB'
        for db_entry in self.contract_db.find_all():
            print 'tenant:', db_entry.tenant_name, 'contract:', db_entry.contract_name
        assert contract_count == len(self.contract_db.find_all())

    def get_contracts(self):
        return self.contract_db.find_all()

    def get_contract(self, tenant_name, contract_name):
        return self.contract_db.find_entry(tenant_name, contract_name)

    def exports_epg(self, epg):
        """
        Checks if a site is exporting a given EPG

        :param epg: Instance of EPG class to check if being exported
        :returns:  True or False.  True if the site is exporting the EPG, False otherwise.
        """
        app = epg.get_parent()
        tenant = app.get_parent()
        epg_db_entries = self.epg_db.find_entries(tenant.name, app.name, epg.name)
        if len(epg_db_entries) == 0:
            return False
        for epg_db_entry in epg_db_entries:
            contract_db_entry = self.contract_db.find_entry(tenant.name, epg_db_entry.contract_name)
            if contract_db_entry is None:
                continue
            if contract_db_entry.is_exported():
                return True
        return False

    def get_all_provided_contracts(self, epg):
        resp = []
        app = epg.get_parent()
        tenant = app.get_parent()
        epg_db_entries = self.epg_db.find_entries(tenant.name, app.name, epg.name)
        for epg_db_entry in epg_db_entries:
            contract_db_entry = self.contract_db.find_entry(tenant.name, epg_db_entry.contract_name)
            resp.append(epg_db_entry)
        return resp

    def _populate_epgs_from_apic(self):
        resp = []
        contracts = self.get_contracts()
        tenants = Tenant.get_deep(self.session,
                                  limit_to=['vzBrCP', 'fvTenant', 'fvAp',
                                            'fvAEPg', 'fvRsProv', 'fvRsCons'])
        for contract in contracts:
            if contract.is_exported() or contract.is_imported():
                for tenant in tenants:
                    if tenant.name == contract.tenant_name:
                        contract_objs = tenant.get_children(Contract)
                        for contract_obj in contract_objs:
                            if contract_obj.name == contract.contract_name:
                                break
                        apps = tenant.get_children(AppProfile)
                        for app in apps:
                            epgs = app.get_children(EPG)
                            for epg in epgs:
                                if epg.does_provide(contract_obj) or epg.does_consume(contract_obj):
                                    entry = EpgDBEntry()
                                    entry.tenant_name = tenant.name
                                    entry.app_name = app.name
                                    entry.epg_name = epg.name
                                    entry.contract_name = contract_obj.name
                                    if entry not in self.epg_db.find_all():
                                        self.epg_db.add_entry(entry)

    def get_epgs(self):
        return self.epg_db.find_all()

    def _populate_endpoints_from_apic(self):
        pass

    def initialize_from_apic(self):
        assert self.logged_in

        # Clear existing DB data
        self.contract_db = ContractDB()
        self.epg_db = EpgDB()

        # Get the latest data from the APIC
        self._populate_contracts_from_apic()
        self._populate_epgs_from_apic()
        self._populate_endpoints_from_apic()

        # Push the EPGs for imported contracts
        # (in case they were imported during a downtime)
        self.export_epgs_consuming_imported_contract()

    # def get_contract_names(self, tenant, app, epg):
    #     resp = []
    #     print 'get_contract_names', self.exported_epgs
    #     print 'looking for', tenant, app, epg
    #     for my_epg in self.exported_epgs:
    #         (tenant_name, app_name, epg_name, contract_name, remote_site_names) = my_epg
    #         # TODO ignoring tenant name for now due to hardcoded difference
    #         if app_name == app and epg_name == epg:
    #             resp.append(contract_name)
    #     return resp

    # def extract_contract(self, contract_name, tenant_name):
    #
    #     pass

    def unexport_contract(self, contract_name, tenant_name, remote_site):
        print 'unexport_contract'
        print 'tenant:', type(tenant_name), tenant_name, 'remote site:', remote_site
        # Remove providing EPGs from remote site
        epg_db_entries = self.epg_db.find_epgs_using_contract(tenant_name, contract_name)
        unexport_tenant = Tenant(str(tenant_name))
        for epg_db_entry in epg_db_entries:
            for app in unexport_tenant.get_children(AppProfile):
                app_already_added = False
                if epg_db_entry.app_name == app.name:
                    unexport_epg = EPG(epg_db_entry.epg_name, app)
                    app_already_added = True
            if not app_already_added:
                unexport_app = AppProfile(epg_db_entry.app_name, unexport_tenant)
                unexport_epg = EPG(epg_db_entry.epg_name, unexport_app)
            unexport_epg.mark_as_deleted()

        print 'EPGs to delete:', unexport_tenant.get_json()

        # Remove contract from remote site
        unexport_contract = Contract(contract_name, unexport_tenant)
        unexport_contract.mark_as_deleted()

        # TODO: Filters need to be removed

        # Remove tag from tenant in remote site

        # Remove tag locally from tenant

        # Need to know the site, contract, and EPGs
        raise NotImplementedError  # TODO
        pass

    def export_epg_providing_contract(self):
        # need tenant/app/epg, contract provided, remote_site
        pass

    def export_epgs_consuming_imported_contract(self):
        print 'export_epgs_consuming_imported_contract'
        tenants = Tenant.get_deep(self.session, limit_to=['fvTenant', 'tagInst', 'vzBrCP',
                                                          'fvAp', 'fvAEPg', 'fvRsCons'],
                                  config_only=True)
        for tenant in tenants:
            tags = tenant.get_tags()
            for tag in tags:
                if not MultisiteTag.is_multisite_tag(tag):
                    continue
                mtag = MultisiteTag.fromstring(tag)
                if mtag.is_imported():
                    print 'Need to export EPGs for ', tenant.name, 'contract', mtag.get_local_contract_name()
                    for contract in tenant.get_children(Contract):
                        if contract.name == mtag.get_local_contract_name():
                            break
                    for app in tenant.get_children(AppProfile):
                        for epg in app.get_children(EPG):
                            if epg.does_consume(contract):
                                print 'EPG ', epg.name, 'does consume contract', contract.name
                                export_tenant = Tenant(tenant.name)
                                export_app = AppProfile(app.name, export_tenant)
                                export_epg = EPG(epg.name, export_app)
                                export_tag = MultisiteTag(contract.name, 'imported', self.name)
                                export_epg.add_tag(str(export_tag))
                                export_contract = Contract(export_tag.get_contract_name(), export_tenant)
                                export_epg.consume(export_contract)
                                export_site = self.my_collector.get_site(mtag.get_remote_site_name())
                                if export_site is not None:
                                    resp = export_tenant.push_to_apic(export_site.session)
                                    print resp, resp.text
        self.epg_db.print_db()

    def export_contract(self, contract_name, tenant_name, remote_sites):
        problem_sites = []

        # get the old contract data
        old_entry = self.contract_db.find_entry(tenant_name, contract_name)
        contract_json = None

        # compare new remote sites list to old list for new sites to export
        for remote_site in remote_sites:
            if remote_site in old_entry.remote_sites:
                continue
            if remote_site not in old_entry.remote_sites:
                # New site that needs to be exported
                if contract_json is None:
                    # only grab the contract configuration once
                    contract_json = self.contract_collector.get_contract_config(str(tenant_name),
                                                                                str(contract_name))
                # Export to the remote site
                resp = self.contract_collector.export_contract_config(contract_json,
                                                                      contract_name,
                                                                      self.my_collector.get_site(remote_site))
                if not resp.ok:
                    problem_sites.append(remote_site)
                else:
                    # Now tag the local tenant
                    tenant = Tenant(str(tenant_name))
                    tenant.add_tag(self.contract_collector.get_local_tag(contract_name, remote_site))
                    tenant.push_to_apic(self.session)

        # compare old site list with new for sites no longer being exported to
        for old_site in old_entry.remote_sites:
            if old_site not in remote_sites:
                self.unexport_contract(contract_name, tenant_name, old_site)

        # update the ContractDB
        for problem_site in problem_sites:
            remote_sites.remove(problem_site)
        for remote_site in remote_sites:
            mtag = MultisiteTag(contract_name, 'exported', remote_site)
            old_entry.add_remote_site(mtag)

        # Update the EPG DB
        self._populate_epgs_from_apic()

        return problem_sites


class RemoteSite(Site):
    def __init__(self, name, credentials):
        super(RemoteSite, self).__init__(name, credentials, local=False)


class MultisiteCollector(object):
    """

    """
    def __init__(self):
        self.sites = []

    def get_sites(self, local_only=False, remote_only=False):
        if local_only:
            locals = []
            for site in self.sites:
                if site.local:
                    locals.append(site)
            return locals
        if remote_only:
            remotes = []
            for site in self.sites:
                if not site.local:
                    remotes.append(site)
            return remotes

        else:
            return self.sites

    def get_local_site(self):
        local_sites = self.get_sites(local_only=True)
        if len(local_sites):
            return local_sites[0]
        else:
            return None

    def get_site(self, name):
        for site in self.sites:
            if site.name == name:
                return site

    def get_num_sites(self):
        return len(self.sites)

    def add_site(self, name, credentials, local):
        self.delete_site(name)
        if local:
            site = LocalSite(name, credentials, self)
        else:
            site = RemoteSite(name, credentials)
            # TODO temporary hack to pass RemoteSite to Monitor
            for previous_site in self.sites:
                if isinstance(previous_site, LocalSite):
                    previous_site.monitor.remote_sites.append(site)
        self.sites.append(site)
        site.start()

    def delete_site(self, name):
        for site in self.sites:
            if name == site.name:
                site.shutdown()
                self.sites.remove(site)

    def print_sites(self):
        print '****MICHSMIT**** Number of sites:', len(self.sites)
        for site in self.sites:
            print site.name, site.credentials.ip_address

def main():
    """
    Main execution routine when run standalone (i.e. not GUI)

    :return: None
    """
    pass

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass