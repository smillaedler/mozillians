# -*- coding: utf-8 -*-

import json

from django.contrib.auth.models import User

from funfactory.urlresolvers import reverse
from nose.tools import eq_
from pyquery import PyQuery as pq

import apps.common.tests.init

from ..cron import assign_autocomplete_to_groups
from ..helpers import stringify_groups
from ..models import AUTO_COMPLETE_COUNT, Group, GroupAlias
from ..utils import merge_groups


class GroupTest(apps.common.tests.init.ESTestCase):
    """Test the group/grouping system."""

    def setUp(self):
        super(GroupTest, self).setUp()
        self.NORMAL_GROUP = Group.objects.create(name='cheesezilla')
        self.SYSTEM_GROUP = Group.objects.create(name='ghost', system=True)

    def test_default_groups(self):
        """Ensure the user has the proper amount of groups upon
        creation.

        """

        assert not self.mozillian.get_profile().groups.all(), (
                'User should have no groups by default.')

    def test_autocomplete_api(self):
        r = self.mozillian_client.get(reverse('group_search'),
                                      dict(term='daft'),
                                      HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        eq_(r['Content-Type'], 'application/json', 'api uses json header')
        assert not 'daft_punk' in json.loads(r.content)

        # Make enough users in a group to trigger the autocomplete
        robots = Group.objects.create(name='daft_punk')
        for i in range(0, AUTO_COMPLETE_COUNT + 1):
            email = 'tallowen%s@example.com' % (str(i))
            user = User.objects.create_user(email.split('@')[0], email)
            user.is_active = True
            user.save()
            profile = user.get_profile()
            profile.groups.add(robots)

        assign_autocomplete_to_groups()
        r = self.mozillian_client.get(reverse('group_search'),
                                      dict(term='daft'),
                                      HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        assert 'daft_punk' in json.loads(r.content)

    def test_groups_are_always_lowercase(self):
        """Ensure all groups are saved with lowercase names only."""
        Group.objects.create(name='lowercase')
        Group.objects.create(name='Uppercase')
        Group.objects.create(name='YELLING')

        # Make sure groups created from a profile are lowercase too.
        profile = self.mozillian.get_profile()
        profile.groups.create(name='ILIKEITLOUD')

        for g in Group.objects.all():
            assert g.name == g.name.lower(), 'All groups should be lowercase.'

    def test_groups_are_case_insensitive(self):
        """Ensure groups are case insensitive."""
        profile = self.mozillian.get_profile()

        data = self.data_privacy_fields.copy()
        data.update(dict(full_name='tofumatt', country='pl',
                         username='tofumatt',
                         groups='Awesome,foo,Bar'))
        self.mozillian_client.post(reverse('profile.edit'), data, follow=True)
        eq_(3, profile.groups.count(), 'Three groups should be saved.')

        group_string = stringify_groups(profile.groups.all())

        for g in ['awesome', 'bar', 'foo']:
            assert g in group_string, (
                    'All three saved groups should be lowercase.')
        assert not 'Awesome' in group_string, (
                'Uppercase group should be transformed to lowercase.')

        # Make an AJAX request for a group using a capital letter.
        r = self.mozillian_client.get(reverse('group_search'),
                                      dict(term='Awesome'),
                                      HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        for g in json.loads(r.content):
            assert g.name == g.name.lower(), (
                    'Group search is case-insensitive.')

    def test_pending_user_can_add_groups(self):
        """Ensure pending users can add/edit groups."""
        profile = self.pending.get_profile()
        assert not profile.groups.all(), 'User should have no groups.'

        data = self.data_privacy_fields.copy()
        data.update(dict(full_name='McAwesomepants', country='pl',
                         username='tofumatt1',
                         groups='Awesome foo Bar'))
        self.pending_client.post(reverse('profile.edit'), data, follow=True)

        assert profile.groups.all(), (
                "Pending user should be able to edit groups.")

    def test_string_split_works_properly(self):
        """Ensure groups are saved correctly from a comma-delimited
        string.

        """
        profile = self.pending.get_profile()
        profile.groups.clear()
        assert not profile.groups.all(), (
                'User has no groups at beginning of test.')

        data = self.data_privacy_fields
        data.update(dict(full_name='McAwesomepants', country='pl',
                         username='tofumatt',
                         groups='Awesome,,foo bar,  Bar,g '))
        self.pending_client.post(reverse('profile.edit'), data, follow=True)

        eq_(4, profile.groups.count(), 'User should have four groups.')
        assert profile.groups.get(name='foo bar'), (
                'Group should contain spaces.')
        for g in profile.groups.all():
            assert not g.name.startswith(u' '), (
                    'Group should not start with a space.')
            assert not g.name.endswith(u' '), (
                    'Group should not end with a space.')

    def test_users_cant_add_system_groups(self):
        """Make sure users can't add system groups to their profile."""
        profile = self.mozillian.get_profile()
        data = self.data_privacy_fields.copy()
        data.update(dict(full_name='tofumatt', country='pl', username='tofumatt',
                         groups='%s %s' % (self.NORMAL_GROUP.name,
                                           self.SYSTEM_GROUP.name)))
        self.mozillian_client.post(reverse('profile.edit'), data, follow=True)

        groups = profile.groups.all()

        eq_(1, len(groups), 'Only one group should have been added.')

        for g in groups:
            assert not g.system, (
                    "None of this user's groups should be system groups.")

    def test_users_cant_remove_system_groups(self):
        """Make sure removing groups in a profile doesn't delete
        system groups.

        When a user deletes their (visible) groups in the edit profile page,
        they shouldn't delete any system groups.

        """
        profile = self.mozillian.get_profile()

        profile.groups.add(self.NORMAL_GROUP, self.SYSTEM_GROUP)
        eq_(2, profile.groups.count(), 'User should have both groups.')

        # Edit this user's profile and remove a group.
        self.mozillian_client.login(email=self.mozillian.email)
        data = self.data_privacy_fields.copy()
        data.update(dict(full_name="McLovin'", country='pl',
                          username='fo', groups=''))
        response = self.mozillian_client.post(
            reverse('profile.edit'), data, follow=True)

        doc = pq(response.content)
        assert not doc('#id_groups').attr('value'), (
                'User should have no visible groups.')

        assert profile.groups.count(), 'User should not have zero groups.'
        for g in profile.groups.all():
            assert g.system, 'User should only have system groups.'

    def test_toggle_membership_on_group_page(self):
        """Verify a user can join/leave a group on its page.

        Make sure the Join/Leave Group buttons appear on group
        listings for authorized users. Make sure system groups cannot
        be joined via the toggle view and that the buttons don't
        appear there.

        """
        profile = self.mozillian.get_profile()

        response = self.mozillian_client.get(reverse('group',
                                           args=[self.NORMAL_GROUP.url]))
        doc = pq(response.content)

        assert not profile.groups.filter(id=self.NORMAL_GROUP.id), (
                'User should not be in the "%s" group' %
                self.NORMAL_GROUP.name)
        assert "Join Group" in response.content, (
                '"Join Group" button should be present in the response.')

        # Follow the toggle membership form action.
        r = self.mozillian_client.post(doc('#toggle-group').attr('action'),
                                       follow=True)
        doc = pq(r.content)

        assert "Leave Group" in r.content, (
                '"Leave Group" button should be present in the response.')
        assert profile.groups.get(id=self.NORMAL_GROUP.id), (
                'User should be part of the "%s" group' %
                self.NORMAL_GROUP.name)

        # Do it again and they should leave the group.
        r = self.mozillian_client.post(doc('#toggle-group').attr('action'), {},
                             xsfollow=True)
        assert not profile.groups.filter(id=self.NORMAL_GROUP.id), (
                'User should not be in the "%s" group' %
                self.NORMAL_GROUP.name)

        # Test against a system group, where we shouldn't be able to toggle
        # membership.
        response = self.mozillian_client.get(
            reverse('group', args=[self.SYSTEM_GROUP.url]))
        doc = pq(response.content)

        assert not profile.groups.filter(id=self.SYSTEM_GROUP.id), (
                'User should not be in the "%s" group' %
                self.SYSTEM_GROUP.name)
        assert not "Join Group" in response.content, (
                '"Join Group" button should not be present in the response.')

        # Attempt to manually toggle the group membership
        r = self.mozillian_client.post(
            reverse('group_toggle', args=[self.SYSTEM_GROUP.url]), follow=True)
        assert not profile.groups.filter(id=self.SYSTEM_GROUP.id), (
                'User should not be in the "%s" group' %
                self.SYSTEM_GROUP.name)

    def test_group_merging(self):
        """Test group merging."""
        master_group = self.NORMAL_GROUP
        groups = Group.objects.filter(system=True)

        merge_groups(master_group, groups)
        eq_(Group.objects.count(), 1)
        eq_(Group.objects.all()[0], master_group)
        eq_(GroupAlias.objects.count(), 3)
        map(lambda x: eq_(x, master_group.id),
            GroupAlias.objects.values_list('alias', flat=True))

    def test_unique_url(self):
        """Test unique group url.

        Name 'cheesezilla' generates the same url as 'cheeseζιλλα'.
        """
        new_group = Group.objects.create(name=u'cheeseζiλλα')
        self.assertNotEqual(new_group.url, self.NORMAL_GROUP.url)
