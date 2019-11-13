# © 2017 Emanuel Cino - <ecino@compassion.ch>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import json

import mock

from odoo.tests.common import HttpCase
from odoo.tools import config

mock_base_send = 'odoo.addons.mail.models.mail_mail.MailMail.send'
mock_sendgrid_api_client = 'odoo.addons.mail_sendgrid.models.mail_mail' \
                           '.SendGridAPIClient'
mock_sendgrid_send = 'odoo.addons.mail_sendgrid.models.mail_mail.MailMail' \
                     '.send_sendgrid'
mock_config = 'odoo.addons.mail_sendgrid.models.mail_mail.config'
mock_config_template = 'odoo.addons.mail_sendgrid.models.sendgrid_template' \
                       '.config'
mock_template_api_client = 'odoo.addons.mail_sendgrid.models' \
                           '.sendgrid_template.sendgrid.SendGridAPIClient'

STATUS_OK = 202
HOST = '127.0.0.1'
PORT = config['http_port']


class FakeClient(object):
    """ Mock Sendgrid APIClient """
    status_code = STATUS_OK
    body = 'ok'

    def __init__(self):
        self.client = self
        self.mail = self
        self.send = lambda x: FakeClient()

    def post(self, **kwargs):
        return self


class FakeRequest(object):
    """ Simulate a Sendgrid JSON request """

    def __init__(self, data):
        self.jsonrequest = [data]


class FakeTemplateClient(object):
    """ Simulate the Sendgrid Template api"""

    def __init__(self):
        self.client = self
        self.templates = self
        self.body = json.dumps({
            "templates": [{
                "id": "fake_id",
                "name": "Fake Template",
                "generation": "legacy"
            }],
            "versions": [{
                "active": True,
                "html_content": "<h1>fake</h1>",
                "plain_content": "fake",
                "name": "fake"
            }],
        })

    def get(self, query_params=None):
        return self

    def _(self, val):
        return self


class TestMailSendgrid(HttpCase):
    def setUp(self):
        super(TestMailSendgrid, self).setUp()
        self.sendgrid_template = self.env['sendgrid.template'].create({
            'name': 'Test Template',
            'remote_id': 'a74795d7-f926-4bad-8e7a-ae95fabd70fc',
            'html_content': '<h1>Test Sendgrid</h1>{{body}}\n{{footer}}'
        })
        self.mail_template = self.env['mail.template'].create({
            'name': 'Test Template',
            'model_id': self.env.ref('base.model_res_partner').id,
            'subject': 'Test e-mail',
            'body_html': 'Dear ${object.name}, hello!',
            'sendgrid_template_ids': [
                (0, 0, {'lang': 'en_US', 'sendgrid_template_id':
                        self.sendgrid_template.id})],
            'auto_delete': False
        })
        self.recipient = self.env.ref('base.partner_demo')
        self.mail_wizard = self.env['mail.compose.message'].create({
            'template_id': self.mail_template.id,
            'composition_mode': 'mass_mail',
            'model': 'res.partner',
            'res_id': self.recipient.id,
            'auto_delete': False
        }).with_context(active_id=self.recipient.id)
        self.mail_wizard.onchange_template_id_wrapper()
        self.timestamp = '1471021089'
        self.event = {
            'timestamp': self.timestamp,
            'sg_event_id': "f_JoKtrLQaOXUc4thXgROg",
            'email': self.recipient.email,
            'odoo_db': self.env.cr.dbname,
            'odoo_id': '<xxx.xxx.xxx-openerp-xxx-res.partner@test_db>'
        }
        self.metadata = {
            'ip': '127.0.0.1',
            'user_agent': False,
            'os_family': False,
            'ua_family': False,
        }
        self.request = FakeRequest(self.event)

    def create_email(self, vals=None):
        mail_vals = self.mail_wizard.get_mail_values(self.recipient.ids)[
            self.recipient.id]
        mail_vals['recipient_ids'] = [(6, 0, self.recipient.ids)]
        mail_vals['headers'] = {'X-Mock': '200'}

        if vals is not None:
            mail_vals.update(vals)

        try:
            return self.env['mail.mail'].with_context(test_mode=True).create(
                mail_vals)
        except RuntimeError as e:
            mail_vals = {k: str(v) for k, v in mail_vals.items()}
            return self.env['mail.mail'].with_context(test_mode=True).create(
                mail_vals)

    def test_preview(self):
        """
        Test the preview email_template is getting the Sendgrid template
        """
        preview_wizard = self.env['email_template.preview'].with_context(
            template_id=self.mail_template.id,
            default_res_id=self.recipient.id
        ).create({})
        # For a strange reason, res_id is converted to string
        preview_wizard.res_id = self.recipient.id
        preview_wizard.on_change_res_id()
        self.assertIn('<h1>Test Sendgrid</h1>', preview_wizard.body_html)
        self.assertIn(self.recipient.name, preview_wizard.body_html)

    def test_substitutions(self):
        """ Test substitutions in templates. """
        self.assertEqual(self.sendgrid_template.detected_keywords, "footer")
        self.mail_template.update_substitutions()
        substitutions = self.mail_template.substitution_ids
        self.assertEqual(len(substitutions), 1)
        self.assertEqual(substitutions.key, 'footer')

    def test_create_email(self):
        """ Test that Sendgrid template is pushed in e-mail. """
        self.mail_template.update_substitutions()
        mail_values = self.mail_wizard.get_mail_values(self.recipient.ids)[
            self.recipient.id]
        # Test Sendgrid HTML preview
        self.assertEqual(
            self.mail_wizard.body_sendgrid,
            self.sendgrid_template.html_content.replace(
                '{{body}}', mail_values['body'])
        )
        mail = self.env['mail.mail'].create(mail_values)
        self.assertEqual(mail.sendgrid_template_id.id,
                         self.sendgrid_template.id)
        self.assertEqual(len(mail.substitution_ids), 1)

    @mock.patch(mock_base_send)
    @mock.patch(mock_sendgrid_send)
    def test_send_email_default(self, mock_sendgrid, mock_email):
        """ Tests that sending an e-mail by default doesn't use Sendgrid,
            and that Sendgrid is used when system parameter is set.
        """
        self.env['ir.config_parameter'].set_param(
            'mail_sendgrid.send_method', False)
        mock_sendgrid.return_value = True
        mock_email.return_value = True
        mail = self.create_email()
        response = mail.send()
        self.assertTrue(response)
        self.assertTrue(mock_email.called)
        self.assertFalse(mock_sendgrid.called)

        self.env['ir.config_parameter'].set_param(
            'mail_sendgrid.send_method', 'sendgrid')
        # Force again computation of send_method
        self.env.clear()
        response = mail.send()
        self.assertTrue(response)
        self.assertEqual(mock_email.call_count, 1)
        self.assertEqual(mock_sendgrid.call_count, 1)

    @mock.patch(mock_sendgrid_api_client)
    @mock.patch(mock_config)
    def test_mail_tracking(self, m_config, mock_sendgrid):
        """ Test various tracking events. """
        mock_sendgrid.return_value = FakeClient()
        mock_sendgrid.send.return_value = STATUS_OK

        self.env['ir.config_parameter'].set_param('mail_sendgrid.send_method',
                                                  'sendgrid')

        # Send mail
        mail = self.create_email()
        response = mail.send(mail)

        self.assertTrue(response)
        self.assertEqual(mock_sendgrid.called, True)
        self.assertEqual(mail.state, 'sent')
        mail_tracking = mail.tracking_email_ids
        self.assertEqual(len(mail_tracking), 1)
        self.assertFalse(mail_tracking.state)

        # Test mail processed
        self.event.update({
            'event': 'processed',
            'odoo_id': mail.message_id
        })
        response = self.env['mail.tracking.email'].event_process(
            self.request, self.event, self.metadata)
        self.assertEqual(response, 'OK')
        self.assertEqual(mail_tracking.state, 'sent')

        # Test mail delivered
        self.event['event'] = 'delivered'
        self.env['mail.tracking.email'].event_process(
            self.request, self.event, self.metadata)
        self.assertEqual(mail_tracking.state, 'delivered')
        self.assertEqual(mail_tracking.recipient, self.recipient.email)
        self.assertFalse(mail.opened)

        # Test mail opened
        self.event['event'] = 'open'
        self.env['mail.tracking.email'].event_process(
            self.request, self.event, self.metadata)
        self.assertEqual(mail_tracking.state, 'opened')
        self.assertTrue(mail.opened)

        # Test click e-mail
        self.event['event'] = 'click'
        self.env['mail.tracking.email'].event_process(
            self.request, self.event, self.metadata)
        self.assertEqual(mail_tracking.state, 'opened')
        self.assertEqual(mail.click_count, 1)

        # Test events are linked to e-mail
        mail.env.clear()
        self.assertEqual(len(mail.tracking_event_ids), 4)

    def test_controller(self):
        """ Check the controller is working """
        event_data = [self.event]
        result = self.json_open(
            '/mail/tracking/sendgrid/' + self.session.db,
            json.dumps(event_data)
        )
        self.assertTrue(result)
        # Invalid request
        result = self.json_open(
            '/mail/tracking/sendgrid/' + self.session.db,
            "[{'invalid': True}]"
        )
        self.assertTrue(result)

    @mock.patch(mock_template_api_client)
    @mock.patch(mock_config_template)
    def test_update_templates(self, m_config, m_sendgrid):
        m_config.return_value = "ldkfjsOIWJRksfj"
        m_sendgrid.return_value = FakeTemplateClient()
        self.env['sendgrid.template'].update_templates()
        template = self.env['sendgrid.template'].search([
            ('remote_id', '=', 'fake_id')
        ])
        self.assertTrue(template)

    def json_open(self, url, data=None, timeout=5):
        if url.startswith('/'):
            url = f"http://{HOST}:{PORT}{url}"
        if data:
            return self.opener.post(url, json=data, timeout=timeout)
        return self.opener.get(url, timeout=timeout)

    def tearDown(self):
        super(TestMailSendgrid, self).tearDown()
        self.env['ir.config_parameter'].set_param(
            'mail_sendgrid.send_method', 'traditional')
