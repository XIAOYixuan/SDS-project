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

from collections import defaultdict
from dataclasses import field
from typing import List, Dict
from random import shuffle

from services.service import PublishSubscribe
from services.service import Service
from utils import SysAct, SysActionType
from utils.beliefstate import BeliefState
from utils.domain.jsonlookupdomain import JSONLookupDomain, TellerDomain
from utils.logger import DiasysLogger
from utils.useract import UserActionType


class HandcraftedPolicy(Service):
    """ Base class for handcrafted policies.

    Provides a simple rule-based policy. Can be used for any domain where a user is
    trying to find an entity (eg. a course from a module handbook) from a database
    by providing constraints (eg. semester the course is offered) or where a user is
    trying to find out additional information about a named entity.

    Output is a system action such as:
     * `inform`: provides information on an entity
     * `request`: request more information from the user
     * `bye`: issue parting message and end dialog

    In order to create your own policy, you can inherit from this class.
    Make sure to overwrite the `choose_sys_act`-method with whatever additionally
    rules/functionality required.

    """

    def __init__(self, domain: JSONLookupDomain, logger: DiasysLogger = DiasysLogger(),
                 max_turns: int = 25):
        """
        Initializes the policy

        Arguments:
            domain {domain.jsonlookupdomain.JSONLookupDomain} -- Domain

        """
        self.first_turn = True
        Service.__init__(self, domain=domain)
        self.current_suggestions = []  # list of current suggestions
        self.s_index = 0  # the index in current suggestions for the current system reccomendation
        self.domain_key = domain.get_primary_key()
        self.logger = logger
        self.max_turns = max_turns

    def dialog_start(self):
        """
            resets the policy after each dialog
        """
        self.turns = 0
        self.first_turn = True
        self.current_suggestions = []  # list of current suggestions
        self.s_index = 0  # the index in current suggestions for the current system reccomendation

    @PublishSubscribe(sub_topics=["beliefstate"], pub_topics=["sys_act", "sys_state"])
    def choose_sys_act(self, beliefstate: BeliefState) \
            -> dict(sys_act=SysAct):

        """
            Responsible for walking the policy through a single turn. Uses the current user
            action and system belief state to determine what the next system action should be.

            To implement an alternate policy, this method may need to be overwritten

            Args:
                belief_state (BeliefState): a BeliefState obejct representing current system
                                           knowledge

            Returns:
                (dict): a dictionary with the key "sys_act" and the value that of the systems next
                        action

        """
        self.turns += 1
        # do nothing on the first turn --LV
        sys_state = {}
        self.logger.info("receiving a belief state")
        if self.first_turn and not beliefstate['user_acts']:
            self.first_turn = False
            sys_act = SysAct()
            sys_act.type = SysActionType.Welcome
            sys_state["last_act"] = sys_act
            self.logger.info("this's the first turn, and user did nothing, so let's welcom")
            print('sys_act', sys_act, 'sys_state', sys_state)
            return {'sys_act': sys_act, "sys_state": sys_state}

        # Handles case where it was the first turn, but there are user acts
        elif self.first_turn:
            self.first_turn = False

        if self.turns >= self.max_turns:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bye
            sys_state["last_act"] = sys_act
            self.logger.info(f"match the max_turn {self.max_turns}")
            print('sys_act', sys_act, 'sys_state', sys_state)
            return {'sys_act': sys_act, "sys_state": sys_state}

        # removes hello and thanks if there are also domain specific actions
        self._remove_gen_actions(beliefstate)

        if UserActionType.Bad in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bad

        # if the action is 'bye' tell system to end dialog
        elif UserActionType.Bye in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bye
        # if user only says thanks, ask if they want anything else
        elif UserActionType.Thanks in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.RequestMore
        # If user only says hello, request a random slot to move dialog along
        elif UserActionType.Hello in beliefstate["user_acts"] or UserActionType.SelectDomain in beliefstate["user_acts"]:
            # as long as there are open slots, choose one randomly
            self.logger.info("looks like we got a hello?")
            self.logger.info(f"user act list {beliefstate['user_acts']}")
            if self._get_open_slot(beliefstate):
                sys_act = SysAct()
                sys_act.type = SysActionType.Request
                slot = self._get_open_slot(beliefstate)
                if slot is None:
                    sys_act = SysAct()
                    sys_act.type = SysActionType.RequestMore
                sys_act.add_value(slot)
                self.logger.info("user act hello, we grasp a slot")
                print(slot)
                print("sys_act is ", sys_act)

            # If there are no more open slots, ask the user if you can help with anything else since
            # this can only happen in the case an offer has already been made --LV
            else:
                self.logger.info("looks like slot is done, ask what else can it help, try to launch a new conversation maybe")
                sys_act = SysAct()
                sys_act.type = SysActionType.RequestMore

            # If we switch to the domain, start a new dialog
            if UserActionType.SelectDomain in beliefstate["user_acts"]:
                self.dialog_start()
            self.first_turn = False
        # handle domain specific actions
        else:
            sys_act, sys_state = self._next_action(beliefstate)
        if self.logger:
            self.logger.dialog_turn("System Action: " + str(sys_act))
        if "last_act" not in sys_state:
            sys_state["last_act"] = sys_act
        self.logger.info(f"The final sys act is {sys_act.type} {sys_act.slot_values}")
        return {'sys_act': sys_act, "sys_state": sys_state}

    def _remove_gen_actions(self, beliefstate: BeliefState):
        """
            Helper function to read through user action list and if necessary
            delete filler actions (eg. Hello, thanks) when there are other non-filler
            (eg. Inform, Request) actions from the user. Stores list of relevant actions
            as a class variable

            Args:
                beliefstate (BeliefState): BeliefState object - includes list of all
                                           current UserActionTypes

        """
        act_types_lst = beliefstate["user_acts"]
        # These are filler actions, so if there are other non-filler acions, remove them from
        # the list of action types
        while len(act_types_lst) > 1:
            if UserActionType.Thanks in act_types_lst:
                act_types_lst.remove(UserActionType.Thanks)
            elif UserActionType.Bad in act_types_lst:
                act_types_lst.remove(UserActionType.Bad)
            elif UserActionType.Hello in act_types_lst:
                self.logger.info("we're removing hello")
                act_types_lst.remove(UserActionType.Hello)
            else:
                break

    def _query_db(self, beliefstate: BeliefState):
        """Based on the constraints specified, uses the domain to generate the appropriate type
           of query for the database

        Args:
            beliefstate (BeliefState): BeliefState object; contains all given user constraints to date

        Returns:
            iterable: representing the results of the database lookup

        --LV
        """
        # determine if an entity has already been suggested or was mentioned by the user
        name = self._get_name(beliefstate)
        # if yes and the user is asking for info about a specific entity, generate a query to get
        # that info for the slots they have specified
        if name and beliefstate['requests']:
            requested_slots = beliefstate['requests']
            return self.domain.find_info_about_entity(name, requested_slots)
        # otherwise, issue a query to find all entities which satisfy the constraints the user
        # has given so far
        else:
            constraints, _ = self._get_constraints(beliefstate)
            return self.domain.find_entities(constraints)

    def _get_name(self, beliefstate: BeliefState):
        """Finds if an entity has been suggested by the system (in the form of an offer candidate)
           or by the user (in the form of an InformByName act). If so returns the identifier for
           it, otherwise returns None

        Args:
            beliefstate (BeliefState): BeliefState object, contains all known user informs

        Return:
            (str): Returns a string representing the current entity name

        -LV
        """
        name = None
        prim_key = self.domain.get_primary_key()
        if prim_key in beliefstate['informs']:
            possible_names = beliefstate['informs'][prim_key]
            name = sorted(possible_names.items(), key=lambda kv: kv[1], reverse=True)[0][0]
        # if the user is tyring to query by name
        else:
            if self.s_index < len(self.current_suggestions):
                current_suggestion = self.current_suggestions[self.s_index]
                if current_suggestion:
                    name = current_suggestion[self.domain_key]
        return name

    def _get_constraints(self, beliefstate: BeliefState):
        """Reads the belief state and extracts any user specified constraints and any constraints
           the user indicated they don't care about, so the system knows not to ask about them

        Args:
            beliefstate (BeliefState): BeliefState object; contains all user constraints to date

        Return:
            (tuple): dict of user requested slot names and their values and list of slots the user
                     doesn't care about

        --LV
        """
        slots = {}
        # parts of the belief state which don't contain constraints
        dontcare = [slot for slot in beliefstate['informs'] if "dontcare" in beliefstate["informs"][slot]]
        informs = beliefstate["informs"]
        slots = {}
        # TODO: consider threshold of belief for adding a value? --LV
        for slot in informs:
            if slot not in dontcare:
                for value in informs[slot]:
                    slots[slot] = value
        return slots, dontcare

    def _get_open_slot(self, beliefstate: BeliefState):
        """For a hello statement we need to be able to figure out what slots the user has not yet
           specified constraint for, this method returns one of those at random

        Args:
            beliefstate (BeliefState): BeliefState object; contains all user constraints to date

        Returns:
            (str): a string representing a category the system might want more info on. If all
            system requestables have been filled, return none

        """
        filled_slots, _ = self._get_constraints(beliefstate)
        requestable_slots = self.domain.get_system_requestable_slots()
        for slot in requestable_slots:
            if slot not in filled_slots:
                return slot
        return None

    def _next_action(self, beliefstate: BeliefState):
        """Determines the next system action based on the current belief state and
           previous action.

           When implementing a new type of policy, this method MUST be rewritten

        Args:
            beliefstate (BeliefState): BeliefState object; contains all user constraints to date
            of each possible state

        Return:
            (SysAct): the next system action

        --LV
        """
        sys_state = {}
        # Assuming this happens only because domain is not actually active --LV
        if UserActionType.Bad in beliefstate['user_acts'] or beliefstate['requests'] \
                and not self._get_name(beliefstate):
            sys_act = SysAct()
            sys_act.type = SysActionType.Bad
            return sys_act, {'last_act': sys_act}

        elif UserActionType.RequestAlternatives in beliefstate['user_acts'] \
                and not self._get_constraints(beliefstate)[0]:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bad
            return sys_act, {'last_act': sys_act}

        elif self.domain.get_primary_key() in beliefstate['informs'] \
                and not beliefstate['requests']:
            sys_act = SysAct()
            sys_act.type = SysActionType.InformByName
            sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
            return sys_act, {'last_act': sys_act}

        # Otherwise we need to query the db to determine next action
        results = self._query_db(beliefstate)
        sys_act = self._raw_action(results, beliefstate)

        # requests are fairly easy, if it's a request, return it directly
        if sys_act.type == SysActionType.Request:
            if len(list(sys_act.slot_values.keys())) > 0:
                sys_state['lastRequestSlot'] = list(sys_act.slot_values.keys())[0]

        # otherwise we need to convert a raw inform into a one with proper slots and values
        elif sys_act.type == SysActionType.InformByName:
            self._convert_inform(results, sys_act, beliefstate)
            # update belief state to reflect the offer we just made
            values = sys_act.get_values(self.domain.get_primary_key())
            if values:
                # belief_state['system']['lastInformedPrimKeyVal'] = values[0]
                sys_state['lastInformedPrimKeyVal'] = values[0]
            else:
                sys_act.add_value(self.domain.get_primary_key(), 'none')

        sys_state['last_act'] = sys_act
        return (sys_act, sys_state)

    def _raw_action(self, q_res: iter, beliefstate: BeliefState) -> SysAct:
        """Based on the output of the db query and the method, choose
           whether next action should be request or inform

        Args:
            q_res (list): rows (list of dicts) returned by the issued sqlite3 query
            beliefstate (BeliefState): contains all UserActionTypes for the current turn

        Returns:
            (SysAct): SysAct object of appropriate type

        --LV
        """
        sys_act = SysAct()
        # if there is more than one result
        if len(q_res) > 1 and not beliefstate['requests']:
            constraints, dontcare = self._get_constraints(beliefstate)
            # Gather all the results for each column
            temp = {key: [] for key in q_res[0].keys()}
            # If any column has multiple values, ask for clarification
            for result in q_res:
                for key in result.keys():
                    if key != self.domain_key:
                        temp[key].append(result[key])
            next_req = self._gen_next_request(temp, beliefstate)
            if next_req:
                sys_act.type = SysActionType.Request
                sys_act.add_value(next_req)
                return sys_act

        # Otherwise action type will be inform, so return an empty inform (to be filled in later)
        sys_act.type = SysActionType.InformByName
        return sys_act

    def _gen_next_request(self, temp: Dict[str, List[str]], belief_state: BeliefState):
        """
            Calculates which slot to request next based asking for non-binary slotes first and then
            based on which binary slots provide the biggest reduction in the size of db results

            NOTE: If the dataset is large, this is probably not a great idea to calculate each turn
                  it's relatively simple, but could add up over time

            Args:
                temp (Dict[str, List[str]]: a dictionary with the keys and values for each result
                                            in the result set

            Returns: (str) representing the slot to ask for next (or empty if none)
        """
        req_slots = self.domain.get_system_requestable_slots()
        # don't other to cacluate statistics for things which have been specified
        constraints, dontcare = self._get_constraints(belief_state)
        # split out binary slots so we can ask about them second
        req_slots = [s for s in req_slots if s not in dontcare and s not in constraints]
        bin_slots = [slot for slot in req_slots if len(self.domain.get_possible_values(slot)) == 2]
        non_bin_slots = [slot for slot in req_slots if slot not in bin_slots]
        # check if there are any differences in values for non-binary slots,
        # if a slot has multiple values, ask about that slot
        for slot in non_bin_slots:
            if len(set(temp[slot])) > 1:
                return slot
        # Otherwise look to see if there are differnces in binary slots
        return self._highest_info_gain(bin_slots, temp)

    def _highest_info_gain(self, bin_slots: List[str], temp: Dict[str, List[str]]):
        """ Since we don't have lables, we can't properlly calculate entropy, so instead we'll go
            for trying to ask after a feature that splits the results in half as evenly as possible
            (that way we gain most info regardless of which way the user chooses)

            Args:
                bin_slots: a list of strings representing system requestable binary slots which
                           have not yet been specified
                temp (Dict[str, List[str]]: a dictionary with the keys and values for each result
                                            in the result set

            Returns: (str) representing the slot to ask for next (or empty if none)
        """
        diffs = {}
        for slot in bin_slots:
            val1, val2 = self.domain.get_possible_values(slot)
            values_dic = defaultdict(int)
            for val in temp[slot]:
                values_dic[val] += 1
            if val1 in values_dic and val2 in values_dic:
                diffs[slot] = abs(values_dic[val1] - values_dic[val2])
            # If all slots have the same value, we don't need to request anything, return none
        if not diffs:
            return ""
        sorted_diffs = sorted(diffs.items(), key=lambda kv: kv[1])
        return sorted_diffs[0][0]

    def _convert_inform(self, q_results: iter,
                        sys_act: SysAct, beliefstate: BeliefState):
        """Fills in the slots and values for a raw inform so it can be returned as the
           next system action.

        Args:
            q_results (list): Results of SQL database query
            sys_act (SysAct): the act to be modified
            beliefstate(BeliefState): BeliefState object; contains all user constraints to date and
                                      the UserActionTypes for the current turn

        --LV
        """

        if beliefstate["requests"] or self.domain.get_primary_key() in beliefstate['informs']:
            self._convert_inform_by_primkey(q_results, sys_act, beliefstate)

        elif UserActionType.RequestAlternatives in beliefstate['user_acts']:
            self._convert_inform_by_alternatives(sys_act, q_results, beliefstate)

        else:
            self._convert_inform_by_constraints(q_results, sys_act, beliefstate)

    def _convert_inform_by_primkey(self, q_results: iter,
                                   sys_act: SysAct, beliefstate: BeliefState):
        """
            Helper function that adds the values for slots to a SysAct object when the system
            is answering a request for information about an entity from the user

            Args:
                q_results (iterable): list of query results from the database
                sys_act (SysAct): current raw sys_act to be filled in
                beliefstate (BeliefState): BeliefState object; contains all user informs to date

        """
        sys_act.type = SysActionType.InformByName
        if q_results:
            result = q_results[0]  # currently return just the first result
            keys = list(result.keys())[:4]  # should represent all user specified constraints

            # add slots + values (where available) to the sys_act
            for k in keys:
                res = result[k] if result[k] else 'not available'
                sys_act.add_value(k, res)
            # Name might not be a constraint in request queries, so add it
            if self.domain_key not in keys:
                name = self._get_name(beliefstate)
                sys_act.add_value(self.domain_key, name)
        else:
            sys_act.add_value(self.domain_key, 'none')

    def _convert_inform_by_alternatives(
            self, sys_act: SysAct, q_res: iter, beliefstate: BeliefState):
        """
            Helper Function, scrolls through the list of alternative entities which match the
            user's specified constraints and uses the next item in the list to fill in the raw
            inform act.

            When the end of the list is reached, currently continues to give last item in the list
            as a suggestion

            Args:
                sys_act (SysAct): the raw inform to be filled in
                beliefstate (BeliefState): current system belief state

        """
        if q_res and not self.current_suggestions:
            self.current_suggestions = []
            self.s_index = -1
            for result in q_res:
                self.current_suggestions.append(result)

        self.s_index += 1
        # here we should scroll through possible offers presenting one each turn the user asks
        # for alternatives
        if self.s_index <= len(self.current_suggestions) - 1:
            # the first time we inform, we should inform by name, so we use the right template
            if self.s_index == 0:
                sys_act.type = SysActionType.InformByName
            else:
                sys_act.type = SysActionType.InformByAlternatives
            result = self.current_suggestions[self.s_index]
            # Inform by alternatives according to our current templates is
            # just a normal inform apparently --LV
            sys_act.add_value(self.domain_key, result[self.domain_key])
        else:
            sys_act.type = SysActionType.InformByAlternatives
            # default to last suggestion in the list
            self.s_index = len(self.current_suggestions) - 1
            sys_act.add_value(self.domain.get_primary_key(), 'none')

        # in addition to the name, add the constraints the user has specified, so they know the
        # offer is relevant to them
        constraints, dontcare = self._get_constraints(beliefstate)
        for c in constraints:
            sys_act.add_value(c, constraints[c])

    def _convert_inform_by_constraints(self, q_results: iter,
                                       sys_act: SysAct, beliefstate: BeliefState):
        """
            Helper function for filling in slots and values of a raw inform act when the system is
            ready to make the user an offer

            Args:
                q_results (iter): the results from the databse query
                sys_act (SysAct): the raw infor act to be filled in
                beliefstate (BeliefState): the current system beliefs

        """
        # TODO: Do we want some way to allow users to scroll through
        # result set other than to type 'alternatives'? --LV
        if q_results:
            self.current_suggestions = []
            self.s_index = 0
            for result in q_results:
                self.current_suggestions.append(result)
            result = self.current_suggestions[0]
            sys_act.add_value(self.domain_key, result[self.domain_key])
        else:
            sys_act.add_value(self.domain_key, 'none')

        sys_act.type = SysActionType.InformByName
        constraints, dontcare = self._get_constraints(beliefstate)
        for c in constraints:
            # Using constraints here rather than results to deal with empty
            # results sets (eg. user requests something impossible) --LV
            sys_act.add_value(c, constraints[c])


#TODO: move this to a new file
#TODO: uses the sub-pub patter
class TellerCoursePicker:
    """ This class carries all the functions to select the courses
    """
    def __init__(self) -> None:
        self.clear()
        self.day2min = self._build_day2min_mapper()

    def clear(self):
        self.total_credits = 100
        self.brute_force_start = 0
        self.candidates = []
        self.solution = []
        self.time_slots = {} # used to map name to time
        self.user_schedules = []
        self.formats = set()
        self.fields = set()

    
    def update_user_schedules(self, schedules):
        self.user_schedules = schedules

    
    def update_total_credits(self, total_credits):
        self.total_credits = int(total_credits)


    def update_formats(self, formats):
        self.formats = set(formats)
    
    
    def update_fields(self, fields):
        self.fields = set(fields)


    def _random_greedy_select(self, candidates, target_credits):
        # return remaining credits, solution
        # TODO: set this as a parameters
        candidates = candidates
        best_solutions = []
        best_credits = 0
        for i in range(10):
            shuffle(candidates)
            solutions = []
            total_credits = 0
            for couse_id, course in enumerate(candidates):
                if self._has_time_conflicts_for_random(candidates, couse_id):
                    continue
                cur_credit = int(course['Credit'])
                if total_credits + cur_credit > target_credits:
                    break
                solutions.append(course)
                total_credits += cur_credit
            
            if total_credits > best_credits:
                best_credits = total_credits
                best_solutions = solutions
        
        best_names = set([course["Name"] for course in best_solutions])
        return best_credits, best_names


    def _brute_force_find_max(self, candidates, target_credits):
        raise NotImplementedError("brute force search")


    def _search_for_preference(self, names, candidates, target_credits):
        # if the user doesn't provide her preferences, don't do search_for_preference
        if len(names) == 0:
            return 0, set() 
        # filter by name
        new_candidates = [course for course in candidates if course["Name"] in names]
        candidates = new_candidates
        if len(candidates) < self.brute_force_start:
            # can be handled easily by brute-force search
            # the following func find a combination with the max score
            # (but <= meet_credits)
            return self._brute_force_find_max(candidates, target_credits)

        else:
            # use a random and greedy algorithm
            return self._random_greedy_select(candidates, target_credits)


    def _fake_query(self, slot, targets):
        # TODO: should query db!
        if len(targets) == 0:
            return set()

        ret = []
        for course in self.candidates:
            for target in targets:
                if target in course[slot].lower():
                    ret.append(course["Name"])
                    break
        return set(ret)


    def _select_one_solution(self, candidates, field_candidates, format_candidates):
        # stage 1: select the courses that meet both requirements, half total credits
        inter_set = list(field_candidates&format_candidates)
        inter_credits, inter_set_solution = self._search_for_preference(inter_set, candidates, max(3, int(0.5 * self.total_credits)))
        # print("inter_set results", inter_credits, inter_set_solution)
        
        # stage 2: select the course that meet either requirements, half total credits
        union_set = (field_candidates| format_candidates) - inter_set_solution
        union_credits, union_set_solution = self._search_for_preference(union_set, candidates, max(0, self.total_credits - inter_credits))
        # print("union results", union_credits, union_set_solution)


        # stage 3: 
        remain_credits = self.total_credits - inter_credits - union_credits
        
        if remain_credits == 0:
            self.solution = list(inter_set_solution) + list(union_set_solution)
            return self.solution
        
        self.solution = []
        self.stack = []
        self.candidates = []
        for course in candidates:
            course_name = course["Name"]
            if course_name in inter_set_solution or course_name in union_set_solution:
                continue
            self.candidates.append(course)
        # print(f'start brute force, candidates{self.candidates}, remain_credits {remain_credits}') 
        status = self._brute_force_meet_total_credits(0, 0, remain_credits)
        if status:
            self.solution = list(inter_set_solution) + list(union_set_solution) + self.solution
        else:
            self.solution = []
        # print("solution", self.solution)
        return self.solution

    
    def select_courses(self, raw_candidates):
        self.candidates = raw_candidates
        
        # update format
        for candidate in self.candidates:
            candidate["Dates"] = self._change_time_format(candidate)
            candidate["Credit"] = int(candidate["Credit"])
        if len(self.user_schedules) > 0:
            self.user_schedules = self._change_time_format({
                "Name": "User",
                "Dates": ';'.join(self.user_schedules)
            })
        self._remove_user_conflicts()

        # prepare time conflict graph
        # TODO: has memory redundacy, e.g., has both key i+j and j+i 
        self.time_conflict_graph = self._build_time_conflict_relation_graph()

        field_candidates = self._fake_query("Field", self.fields)
        format_candidates = self._fake_query("Format", self.formats)
        # print('--------------------------field format candidates-----------------------------------------')
        # print(type(field_candidates), field_candidates)
        # print(type(format_candidates), format_candidates)
        # print(format_candidates&field_candidates)
        # print('-------------------------------------------------------------------')

        different_solutions = []
        for _ in range(3):
            # 3 trials
            shuffle(self.candidates)
            solution = self._select_one_solution(self.candidates, field_candidates, format_candidates)
            different_solutions.append(solution)
        
        # unique_solutions
        different_solutions = [list(x) for x in set(tuple(x) for x in different_solutions)]
        
        if len(different_solutions) == 1 and len(different_solutions[0]) == 0:
            return []
        
        for sol in different_solutions:
            for i in range(len(sol)):
                sol[i] = (sol[i], self.time_slots[sol[i]])
        return different_solutions


    def _remove_user_conflicts(self):
        new_candidates = []
        for candidate in self.candidates:
            if self._has_overlap(candidate["Dates"], self.user_schedules):
                continue
            new_candidates.append(candidate)
        self.candidates = new_candidates


    def _has_overlap(self, times_a, times_b):
        for a in times_a:
            for b in times_b:
                overlap = max(0, min(a[1], b[1]) - max(a[0], b[0]))
                if overlap > 0:
                    return True
        return False


    def _build_time_conflict_relation_graph(self):
        has_conflicts = {}
        for course_i in self.candidates:
            i = course_i["Name"]
            for course_j in self.candidates:
                j = course_j["Name"]
                if i == j: continue
                has_conflicts[i+"+"+j] = self._has_overlap(course_i["Dates"], course_j["Dates"])
        return has_conflicts


    def _build_day2min_mapper(self):
        days = ["mon", "tue", "wed", "thur", "fri", "sat", "sun"]
        cur_offset = 0
        day2min = {}
        one_day = 24*3600

        for day in days:
            day2min[day] = cur_offset 
            cur_offset += one_day
        return day2min


    def _change_time_format(self, candidate):
        """ Change time format from Date to minutes
        """
        name = candidate["Name"]
        dates = candidate["Dates"].split(";")
        time_slot_in_minutes = []
        for date in dates:
            date = date.strip().lower()
            day, duration = date.split('.')
            day, duration = day.strip(), duration.strip()
            if name not in self.time_slots: 
                self.time_slots[name] = []
            self.time_slots[name].append((day, duration))
            min_offset = self.day2min[day]
            start_time, end_time = duration.split('-')
            start_time, end_time = self._clock2min(start_time), self._clock2min(end_time)
            time_slot_in_minutes.append((min_offset+start_time, min_offset+end_time))
        return time_slot_in_minutes


    def _clock2min(self, clock_time):
        clock_time = clock_time.strip()
        hh, mm = clock_time.split(":")
        hh, mm = int(hh.strip()), int(mm.strip())
        return hh*60 + mm


    def _has_time_conflicts_for_random(self, candidates, course_id: int):
        # TODO: merge two functions
        cur_name = candidates[course_id]["Name"]
        for pid, pre in enumerate(candidates):
            if pid == course_id: break
            pre_name = pre["Name"]
            if pre_name == cur_name: continue
            name_bind = pre_name + "+" + cur_name 
            if self.time_conflict_graph[name_bind]:
                return True
        return False
            

    def _has_time_conflicts(self, course_id: int):
        cur_name = self.candidates[course_id]["Name"]
        for pre in self.stack:
            pre_name = self.candidates[pre]["Name"]
            if pre_name == cur_name:
                continue 
            name_bind = pre_name + "+" + cur_name 
            # TODO: potential bug here
            if name_bind not in self.time_conflict_graph:
                print("error!", name_bind)
                for k in self.time_conflict_graph:
                    print(f"key in graph: {k}")
                
            if self.time_conflict_graph[name_bind]:
                return True
        return False

    
    def _brute_force_meet_total_credits(self, cur_credits = 0, cur_id = 0, total_credits = 0):
        # TODO: add more constraints here
        # TODO: need optimization, pruning
        # TODO: need to maintain a dependency graph, telling the module which courses are choosable
        self.stack.append(cur_id)
        # print(f"brute_forcing: {cur_id} course {self.candidates[cur_id]['Name']} credits {cur_credits}")
        if cur_id >= len(self.candidates):
            # print(f"cur_id {cur_id} > {len(self.candidates)}")
            self.stack.pop()
            return False

        if self._has_time_conflicts(cur_id):
            # print(f'{cur_id} has time conflicts!')
            self.stack.pop()
            return False

        # print(f'cur credits: {cur_credits} total_credits: {total_credits} cur_id : {cur_id}')
        # option 1: choose myself and meet the credits
        new_credit = cur_credits + int(self.candidates[cur_id]['Credit'])
        if new_credit == total_credits:
            self.solution.append(self.candidates[cur_id]['Name'])
            # print(f'1st success new credits: {new_credit} cur_id : {cur_id}')
            self.stack.pop()
            return True
        # option 1: choose myself and need to explore more 
        elif self._brute_force_meet_total_credits(new_credit, cur_id+1, total_credits):
            self.solution.append(self.candidates[cur_id]['Name'])
            # print(f'2nd success new credits: {new_credit} cur_id : {cur_id}')
            self.stack.pop()
            return True
        
        # option 2: don't choose myself
        self.stack.pop()
        if self._brute_force_meet_total_credits(cur_credits, cur_id+1, total_credits):
            # print(f'3rd success new credits: {cur_credits} cur_id : {cur_id}')
            return True
        else:
            # print(f"fail at {cur_id}")
            return False


class TellerPolicy(HandcraftedPolicy):

    def __init__(self, domain: TellerDomain, logger):
        self.first_turn = True
        Service.__init__(self, domain=domain)
        self.logger = logger
        self.current_suggestions = []
        self.s_index = 0
        self.course_picker = TellerCoursePicker()


    def dialog_start(self):
        """ TODO: Reset the policy after each dialog
        """
        self.turns = 0
        self.first_turn = True
        self.current_suggestions = []
        self.s_index = 0
        self.course_picker.clear()
        self.logger.info("hi, policy starts!")


    @PublishSubscribe(sub_topics=["beliefstate"], pub_topics=["sys_act", "sys_state"])
    def choose_sys_act(self, beliefstate):
        self.turns += 1

        # the following block means do nothing for the very 
        # beginning, toggle the sys to say welcome
        sys_state = {}
        if self.first_turn and not beliefstate['user_acts']:
            self.first_turn = False
            sys_act = SysAct()
            sys_act.type = SysActionType.Welcome
            sys_state["last_act"] = sys_act
            return {'sys_act': sys_act, "sys_state": sys_state}
        
        elif self.first_turn:
            self.first_turn = False

        # TODO: when self.turns >= max_turns

        # if there're more than one request/intentions in the 
        # utt, remove the filler act
        # e.g. Hello! I'm looking for ...
        # then remove Hello.
        self._remove_gen_actions(beliefstate)

        if UserActionType.Bad in beliefstate["user_acts"]:
            if "bad" in beliefstate:
                sys_act, sys_state = self.request_for_bad_inform(beliefstate)
                self.logger.info(f"sys act meta: {sys_act.meta}")
            else:
                sys_act = self.add_open_slot(beliefstate)
                if sys_act is None:
                    sys_act = SysAct()
                    sys_act.type = SysActionType.RequestMore
                # sys_act = SysAct()
                # sys_act.type = SysActionType.Bad
        # if the action is 'bye' tell system to end dialog
        elif UserActionType.Bye in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bye
        elif UserActionType.Thanks in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.RequestMore
        elif UserActionType.Hello in beliefstate["user_acts"]:
            # if user only says hello, ask how many credits
            # they want to earn for the next semester. if
            # that slot is answered, then grasp another open
            # slot
            sys_act = self.add_open_slot(beliefstate)
            if sys_act is None:
                sys_act = SysAct()
                sys_act.type = SysActionType.RequestMore
        elif UserActionType.Inform in beliefstate["user_acts"]:
            self.logger.info("we found an INFORM!")
            #TODO: if there's an inform, there must also be a high-lvl inform
            sys_act, sys_state = self._next_action(beliefstate)
        else:
            self.logger.info("ERROR: sorry, unk type")
            exit(0)

        # TODO: when will last_act be in sys_state
        if "last_act" not in sys_state:
            sys_state["last_act"] = sys_act

        return {'sys_act': sys_act, 'sys_state': sys_state}
    

    def request_for_bad_inform(self, beliefstate: BeliefState):
        """ TODO: Only handle the first bad inform for now
        """
        sys_act = SysAct()
        sys_act.type = SysActionType.Request
        slot = beliefstate['bad'][0]
        sys_act.add_value(slot)
        sys_act.meta["error"] = slot

        sys_state = {
                    "last_act": sys_act,
                    "lastRequestSlot": [slot]
                }
        return sys_act, sys_state


    def _next_action(self, beliefstate: BeliefState):
        slots = self.domain.high_level_slots()
        for slot in slots:
            value = beliefstate.get_high_level_inform_value(slot)
            if value is None:
                sys_act = SysAct()
                sys_act.type = SysActionType.Request
                sys_act.add_value(slot)

                sys_state = {
                    "last_act": sys_act, 
                    "lastRequestSlot": list(sys_act.slot_values.keys())}
                return sys_act, sys_state
            elif not self._input_validation(slot, value):
                sys_act = SysAct(SysActionType.Request)
                sys_act.add_value('error', slot)

                sys_state = {
                    "last_act": sys_act,
                    "lastRequestSlot": [slot]
                }
                return sys_act, sys_state

        sys_act = SysAct()
        sys_act.type = SysActionType.InformByName
        self.course_picker.clear()
        candidates = self._query_db(beliefstate)
        for slot in slots:
            # TODO: func dictionary
            if slot == self.domain.total_credits:
                self._process_total_credits(beliefstate, sys_act)
            elif slot == self.domain.user_schedules:
                self._process_user_schedules(beliefstate, sys_act)
            elif slot == self.domain.fields:
                self._process_field_preference(beliefstate, sys_act)
            elif slot == self.domain.formats:
                self._process_format_preference(beliefstate, sys_act)
            else:
                raise NotImplementedError(f"unknown slot {slot}")
        
        solutions = self.course_picker.select_courses(candidates)
        for sol in solutions:
            sys_act.add_value('courses', sol)

        if len(solutions) == 0:
            raise NotImplementedError("no solution, should set sys act to Bad or Inform?")

        return sys_act, {"last_act": sys_act}


    def _input_validation(self, slot, value):
        if slot == self.domain.total_credits:
            value = int(value)
            return value % 3 == 0 and value > 0
        else:
            #TODO
            return True 
    
    
    def _query_db(self, beliefstate: BeliefState):
        """ Query the courses whose credits <= total credits
        TODO: query the courses with specific field
        """
        # when there's a primary name
        # name = self._get_name(beliefstate)
        results = []
        if len(beliefstate["informs"]) != 0:
            results = super()._query_db(beliefstate)
        else:
            high_level_dict = beliefstate["high_level_informs"]
            for slot in high_level_dict: 
                for constraint in high_level_dict[slot][-1]:
                    cur_results = self.domain.find_entities(constraint)
                    results += cur_results
        # self.logger.info(f"results for query: {results}")
        results = self.domain.uniq_list(results)
        return results 
    
    
    def _process_total_credits(self, beliefstate: BeliefState, sys_act: SysAct):
        total_credits = beliefstate.get_high_level_inform_value(self.domain.total_credits)
        total_credits = int(total_credits)
        self.course_picker.update_total_credits(total_credits)
        sys_act.add_value(self.domain.total_credits, total_credits)


    def _process_user_schedules(self, beliefstate: BeliefState, sys_act: SysAct):
        # add all schedules to user_schedules
        high_lvl_slot = self.domain.user_schedules
        self._add_batch_values(beliefstate, high_lvl_slot, sys_act)
        self.course_picker.update_user_schedules(sys_act.get_values(high_lvl_slot))
    

    def _process_field_preference(self, beliefstate: BeliefState, sys_act: SysAct):
        self._add_batch_values(beliefstate, self.domain.fields, sys_act)
        fields = sys_act.get_values(self.domain.fields)
        self.course_picker.update_fields(fields) 


    def _process_format_preference(self, beliefstate: BeliefState, sys_act: SysAct):
        self._add_batch_values(beliefstate, self.domain.fields, sys_act)
        formats = sys_act.get_values(self.domain.formats)
        self.course_picker.update_formats(formats)


    def _add_batch_values(self, beliefstate, high_lvl_slot, sys_act):
        slot_name = self.domain.slot_map[high_lvl_slot]
        for key_val in beliefstate.get_high_level_inform_sub_results(high_lvl_slot):
            sys_act.add_value(high_lvl_slot, key_val[slot_name])


    def add_open_slot(self, beliefstate: BeliefState):
        slot = self._get_open_slot(beliefstate)
        if slot is None:
            return None
        else:
            sys_act = SysAct()
            sys_act.type = SysActionType.Request
            sys_act.add_value(slot)
            return sys_act

    def _get_open_slot(self, beliefstate: BeliefState):
        # TODO
        filled_slots = []
        for slot in beliefstate['high_level_informs']:
            filled_slots.append(slot)
            
        self.logger.info(f'filled_slots {filled_slots}')
        requestable_slots = self.domain.high_level_slots()
        for slot in requestable_slots:
            if slot not in filled_slots:
                return slot
        self.logger.info("Warning, returning a None object.")
        return None