###############################################################################
#
# Copyright 2020, University of Stuttgart: Institute for Natural Language Processing (IMS)
#
# This file is part of Adviser.
# Adviser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3.
#
# Adviser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Adviser.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################


import json
import os
import sqlite3
from io import StringIO
from typing import List, Iterable

from utils.domain import Domain


class JSONLookupDomain(Domain):
    """ Abstract class for linking a domain based on a JSON-ontology with a database
       access method (sqllite).
    """

    def __init__(self, name: str, json_ontology_file: str = None, sqllite_db_file: str = None, \
                 display_name: str = None):
        """ Loads the ontology from a json file and the data from a sqllite
            database.

            To create a new domain using this format, inherit from this class
            and overwrite the _get_domain_name_()-method to return your
            domain's name.

        Arguments:
            name (str): the domain's name used as an identifier
            json_ontology_file (str): relative path to the ontology file
                                (from the top-level adviser directory, e.g. resources/ontologies)
            sqllite_db_file (str): relative path to the database file
                                (from the top-level adviser directory, e.g. resources/databases)
            display_name (str): the domain's name as it appears on the screen
                                (e.g. containing whitespaces)
        """
        super(JSONLookupDomain, self).__init__(name)

        root_dir = self._get_root_dir()
        self.sqllite_db_file = sqllite_db_file
        # make sure to set default values in case of None
        json_ontology_file = json_ontology_file or os.path.join('resources', 'ontologies',
                                                                name + '.json')
        sqllite_db_file = sqllite_db_file or os.path.join('resources', 'databases',
                                                          name + '.db')

        self.ontology_json = json.load(open(root_dir + '/' + json_ontology_file))
        # load database
        self.db = self._load_db_to_memory(root_dir + '/' + sqllite_db_file)

        self.display_name = display_name if display_name is not None else name

    def __getstate__(self):
        # remove sql connection from state dict so that pickling works
        state = self.__dict__.copy()
        if 'db' in state:
            del state['db']
        return state

    def _get_root_dir(self):
        """ Returns the path to the root directory """
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _sqllite_dict_factory(self, cursor, row):
        """ Convert sqllite row into a dictionary """
        row_dict = {}
        for col_idx, col in enumerate(cursor.description):
            # iterate over all columns, get corresponding db value from row
            row_dict[col[0]] = row[col_idx]
        return row_dict

    def _load_db_to_memory(self, db_file_path : str):
        """ Loads a sqllite3 database from file to memory in order to save
            I/O operations

        Args:
            db_file_path (str): absolute path to database file

        Returns:
            A sqllite3 connection
        """

        # open and read db file to temporary file
        file_db = sqlite3.connect(db_file_path, check_same_thread=False)
        tempfile = StringIO()
        for line in file_db.iterdump():
            tempfile.write('%s\n' % line)
        file_db.close()
        tempfile.seek(0)
        # Create a database in memory and import from temporary file
        db = sqlite3.connect(':memory:', check_same_thread=False)
        db.row_factory = self._sqllite_dict_factory
        db.cursor().executescript(tempfile.read())
        db.commit()
        # file_db.backup(databases[domain]) # works only in python >= 3.7

        return db

    def find_entities(self, constraints: dict, requested_slots: Iterable = iter(())):
        """ Returns all entities from the data backend that meet the constraints, with values for
            the primary key and the system requestable slots (and optional slots, specifyable
            via requested_slots).

        Args:
            constraints (dict): Slot-value mapping of constraints.
                                If empty, all entities in the database will be returned.
            requested_slots (Iterable): list of slots that should be returned in addition to the
                                        system requestable slots and the primary key

        """
        # values for name and all system requestable slots
        select_clause = ", ".join(set([self.get_primary_key()]) |
                                  set(self.get_system_requestable_slots()) |
                                  set(requested_slots))
        query = "SELECT {} FROM {}".format(select_clause, self.get_domain_name())
        constraints = {slot: value.replace("'", "''") for slot, value in constraints.items()
                       if value is not None and str(value).lower() != 'dontcare'}
        if constraints:
            query += ' WHERE ' + ' AND '.join("{}='{}' COLLATE NOCASE".format(key, str(val))
                                              for key, val in constraints.items())
        return self.query_db(query)

    def find_info_about_entity(self, entity_id, requested_slots: Iterable):
        """ Returns the values (stored in the data backend) of the specified slots for the
            specified entity.

        Args:
            entity_id (str): primary key value of the entity
            requested_slots (dict): slot-value mapping of constraints

        """
        if requested_slots:
            select_clause = ", ".join(sorted(requested_slots))
        # If the user hasn't specified any slots we don't know what they want so we give everything
        else:
            select_clause = "*"
        query = 'SELECT {} FROM {} WHERE {}="{}";'.format(
            select_clause, self.get_domain_name(), self.get_primary_key(), entity_id)
        return self.query_db(query)

    def query_db(self, query_str):
        """ Function for querying the sqlite3 db

        Args:
            query_str (string): sqlite3 query style string

        Return:
            (iterable): rows of the query response set
        """
        if "db" not in self.__dict__:
            root_dir = self._get_root_dir()
            sqllite_db_file = self.sqllite_db_file or os.path.join(
                'resources', 'databases', self.name + '.db')
            self.db = self._load_db_to_memory(root_dir + '/' + sqllite_db_file)
        cursor = self.db.cursor()
        cursor.execute(query_str)
        res = cursor.fetchall()
        return res

    def get_display_name(self):
        return self.display_name

    def get_requestable_slots(self) -> List[str]:
        """ Returns a list of all slots requestable by the user. """
        return self.ontology_json['requestable']

    def get_system_requestable_slots(self) -> List[str]:
        """ Returns a list of all slots requestable by the system. """
        return self.ontology_json['system_requestable']

    def get_informable_slots(self) -> List[str]:
        """ Returns a list of all informable slots. """
        return self.ontology_json['informable'].keys()

    def get_possible_values(self, slot: str) -> List[str]:
        """ Returns all possible values for an informable slot

        Args:
            slot (str): name of the slot

        Returns:
            a list of strings, each string representing one possible value for
            the specified slot.
         """
        return self.ontology_json['informable'][slot]

    def get_primary_key(self):
        """ Returns the name of a column in the associated database which can be used to uniquely
            distinguish between database entities.
            Could be e.g. the name of a restaurant, an ID, ... """
        return self.ontology_json['key']

    def get_pronouns(self, slot):
        if slot in self.ontology_json['pronoun_map']:
            return self.ontology_json['pronoun_map'][slot]
        else:
            return []

    def get_keyword(self):
        if "keyword" in self.ontology_json:
            return self.ontology_json['keyword']

class TellerDomain(JSONLookupDomain):

    def __init__(self, name, json_ontology_file, sqllite_db_file, display_name):
        """
        Similar to JSONLookupDomain.
        Define the string of all high-level slots.
        Add a dictionary that map high-level slots to their corresponding
        low-level slots.
        """
        super().__init__(name, json_ontology_file, sqllite_db_file, display_name)
        # TODO: add these to avoid typos in other functions
        self.total_credits = "total_credits"
        self.user_schedules = "user_schedules"
        self.fields = "fields"
        self.formats = "formats"
        self.semester = "semester"
        self.slot_map = {
            self.semester: "Sms",
            self.total_credits: "Credit",
            self.user_schedules: "Dates",
            self.fields: "Field",
            self.formats: "Format",
        }

    def high_level_slots(self):
        """ Return the name of high-level slots. 
        A high-level slot cannot be directly found in the db attr list,
        but is related to the ultimate task.
        e.g. the total credit a user need
        """
        # TODO: store the key list somewhere else
        return list(self.slot_map.keys())

    
    def break_down_informs(self, slot_name, value, regex_value):
        """ 
            Break down high level informs to smaller one
            
            total_credits:
                high-level means the total credits user want to earn
                low-level means when querying the database, we need
                    to select all courses whose credit <= total_credits

            user_schedule:
                only change the value mapping(TODO: use the Day. hh:mm format in regex template)

            the others stay the same

        """
        slot_value_pairs = []
        if slot_name not in self.slot_map:
            assert False and "not impl"
        sub_slot = self.slot_map[slot_name]
        
        if slot_name == self.total_credits:
            if not regex_value.isnumeric():
                slot_value_pairs.append({sub_slot: regex_value})
                return slot_value_pairs

            value = int(regex_value)
            
            possible_values = self.get_possible_values(sub_slot)
            for v in possible_values:
                if int(v) > value:
                    continue
                sv = {sub_slot:v}
                slot_value_pairs.append(sv)

        elif slot_name == self.fields or slot_name == self.formats or slot_name == self.semester or slot_name == self.user_schedules:
            slot_value_pairs.append({sub_slot: regex_value})

        return slot_value_pairs


    def uniq_list(self, results):
        """unique the list using the primary key
        """
        uniq_dict = {}
        pkey = self.get_primary_key()
        for item in results:
            uniq_dict[item[pkey]] = item
        results = []
        for key in uniq_dict:
            results.append(uniq_dict[key])
        return results

