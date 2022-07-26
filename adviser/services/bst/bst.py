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

from typing import List, Set

from services.service import PublishSubscribe
from services.service import Service
from utils.beliefstate import BeliefState
from utils.useract import UserActionType, UserAct


class HandcraftedBST(Service):
    """
    A rule-based approach to belief state tracking.
    """

    def __init__(self, domain=None, logger=None):
        Service.__init__(self, domain=domain)
        self.logger = logger
        self.bs = BeliefState(domain)

    @PublishSubscribe(sub_topics=["user_acts"], pub_topics=["beliefstate"])
    def update_bst(self, user_acts: List[UserAct] = None) \
            -> dict(beliefstate=BeliefState):
        """
            Updates the current dialog belief state (which tracks the system's
            knowledge about what has been said in the dialog) based on the user actions generated
            from the user's utterances

            Args:
                user_acts (list): a list of UserAct objects mapped from the user's last utterance

            Returns:
                (dict): a dictionary with the key "beliefstate" and the value the updated
                        BeliefState object

        """
        # save last turn to memory
        self.bs.start_new_turn()
        self.logger.info("updating bst, before")
        print(self.bs)
        if user_acts:
            self._reset_informs(user_acts)
            self._reset_requests()
            self.bs["user_acts"] = self._get_all_usr_action_types(user_acts)
            self._handle_user_acts(user_acts)
            num_entries, discriminable = self.bs.get_num_dbmatches()
            self.bs["num_matches"] = num_entries
            self.bs["discriminable"] = discriminable
        self.logger.info(f"finish update, belif stack is ")
        print(self.bs)
        return {'beliefstate': self.bs}

    def dialog_start(self):
        """
            Restets the belief state so it is ready for a new dialog

            Returns:
                (dict): a dictionary with a single entry where the key is 'beliefstate'and
                        the value is a new BeliefState object
        """
        # initialize belief state
        self.bs = BeliefState(self.domain)

    def _reset_informs(self, acts: List[UserAct]):
        """
            If the user specifies a new value for a given slot, delete the old
            entry from the beliefstate
        """

        slots = {act.slot for act in acts if act.type == UserActionType.Inform}
        for slot in [s for s in self.bs['informs']]:
            if slot in slots:
                del self.bs['informs'][slot]

    def _reset_requests(self):
        """
            gets rid of requests from the previous turn
        """
        self.bs['requests'] = {}

    def _get_all_usr_action_types(self, user_acts: List[UserAct]) -> Set[UserActionType]:
        """ 
        Returns a set of all different UserActionTypes in user_acts.

        Args:
            user_acts (List[UserAct]): list of UserAct objects

        Returns:
            set of UserActionType objects
        """
        action_type_set = set()
        for act in user_acts:
            action_type_set.add(act.type)
        return action_type_set

    def _handle_user_acts(self, user_acts: List[UserAct]):

        """
            Updates the belief state based on the information contained in the user act(s)

            Args:
                user_acts (list[UserAct]): the list of user acts to use to update the belief state

        """
        
        # reset any offers if the user informs any new information
        if self.domain.get_primary_key() in self.bs['informs'] \
                and UserActionType.Inform in self.bs["user_acts"]:
            del self.bs['informs'][self.domain.get_primary_key()]

        # We choose to interpret switching as wanting to start a new dialog and do not support
        # resuming an old dialog
        elif UserActionType.SelectDomain in self.bs["user_acts"]:
            self.bs["informs"] = {}
            self.bs["requests"] = {}

        # Handle user acts
        for act in user_acts:
            if act.type == UserActionType.Request:
                self.bs['requests'][act.slot] = act.score
            elif act.type == UserActionType.Inform:
                # add informs and their scores to the beliefstate
                if act.slot in self.bs["informs"]:
                    self.bs['informs'][act.slot][act.value] = act.score
                else:
                    self.bs['informs'][act.slot] = {act.value: act.score}
            elif act.type == UserActionType.NegativeInform:
                # reset mentioned value to zero probability
                if act.slot in self.bs['informs']:
                    if act.value in self.bs['informs'][act.slot]:
                        del self.bs['informs'][act.slot][act.value]
            elif act.type == UserActionType.RequestAlternatives:
                # This way it is clear that the user is no longer asking about that one item
                if self.domain.get_primary_key() in self.bs['informs']:
                    del self.bs['informs'][self.domain.get_primary_key()]


class TellerBST(HandcraftedBST):

    def __init__(self, domain=None, logger=None):
        Service.__init__(self, domain=domain)
        self.logger = logger
        self.logger.info(f"My domain is {domain}")
        self.bs = BeliefState(domain)


    @PublishSubscribe(sub_topics=["user_acts"], pub_topics=["beliefstate"]) 
    def update_bst(self, user_acts: List[UserAct] = None):
        """
        Return a dict of belief state
        TODO: maybe use the super()'s impl?
        """
        # save last turn to memory
        self.bs.start_new_turn()
        
        if user_acts:
            self.bs['user_acts'] = self._get_all_usr_action_types(user_acts)
            self._handle_user_acts(user_acts)
            num_entries, discriminable = self.bs.get_num_dbmatches()
            self.bs["num_matches"] = num_entries
            self.bs["discriminable"] = discriminable
            self._add_bad_info(user_acts)
        self.logger.info(f"update beliefstate")
        print(self.bs)
        return {'beliefstate': self.bs}


    def _add_bad_info(self, user_acts: List[UserAct]):
        """ Let policy request again
        """
        if "bad" in self.bs:
            self.bs["bad"] = []
        for act in user_acts:
            if act.type != UserActionType.Bad:
                continue
            if act.slot is None:
                continue
            if "bad" not in self.bs:
                self.bs["bad"] = []
            self.bs["bad"].append(act.slot)


    def _handle_user_acts(self, user_acts: List[UserAct]):
        high_dict = self.bs["high_level_informs"]
        for act in user_acts:
            if act.type == UserActionType.Inform and \
                act.slot in self.domain.high_level_slots():

                self._handle_high_level_user_acts(act, high_dict)
            
        self.bs["high_level_informs"] = high_dict

    
    def _handle_high_level_user_acts(self, act: UserAct, high_dict: dict):
        if act.value == "dontcare":
            high_dict[act.slot] = (act.text, [])
        else:
            new_slot_values = self.domain.break_down_informs(act.slot, act.text, act.value)
            if act.slot in high_dict:
                high_dict[act.slot][-1].extend(new_slot_values)
            else:
                high_dict[act.slot] = (act.value, new_slot_values)

    
    def dialog_start(self):
        """ The original comment says it returns the belief state
        for a new dialog, we do nothing atm
        """
        self.logger.info("hey, bst starts working")
        self.bs = BeliefState(self.domain)