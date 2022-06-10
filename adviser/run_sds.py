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

"""
This module allows to chat with the dialog system.
"""

import argparse
from cmath import log
import os
# from SDS.adviser.adviser.services.nlu.nlu import HandcraftedNLU

from services.bst import HandcraftedBST
from services.domain_tracker.domain_tracker import DomainTracker
from services.service import DialogSystem
from utils.logger import DiasysLogger, LogLevel


def load_console():
    from services.hci.console import ConsoleInput, ConsoleOutput
    user_in = ConsoleInput(domain="")
    user_out = ConsoleOutput(domain="")
    return [user_in, user_out]

def load_nlg(backchannel: bool, domain = None, logger=None):
    if backchannel:
        from services.nlg import BackchannelHandcraftedNLG
        nlg = BackchannelHandcraftedNLG(domain=domain, sub_topic_domains={'predicted_BC': ''})
    else:
        from services.nlg.nlg import HandcraftedNLG
        nlg = HandcraftedNLG(domain=domain, logger=logger)
    return nlg

def load_domain(backchannel: bool = False, logger = None):
    from utils.domain.jsonlookupdomain import JSONLookupDomain, TellerDomain
    from services.nlu.nlu import TellerNLU, HandcraftedNLU
    from services.nlg.nlg import TellerNLG, HandcraftedNLG
    from services.policy import TellerPolicy, HandcraftedPolicy
    from services.bst.bst import TellerBST
    use_teller = True
    # use_teller = False 
    if use_teller:
        domain = TellerDomain(name='Courses', json_ontology_file="resources/teller/Courses.json", sqllite_db_file="resources/teller/Courses.db", display_name="Courses")
        nlu = TellerNLU(domain=domain, logger=logger)
        bst = TellerBST(domain=domain, logger=logger)
        policy = TellerPolicy(domain=domain, logger=logger)
        nlg = TellerNLG(domain=domain, logger=logger)
    else:
        domain = JSONLookupDomain('ImsLecturers', display_name="Lecturers")
        nlu = HandcraftedNLU(domain=domain, logger=logger)
        bst = HandcraftedBST(domain=domain, logger=logger)
        policy = HandcraftedPolicy(domain=domain, logger=logger)
        nlg = load_nlg(backchannel=backchannel, domain=domain, logger=logger)
    return domain, [nlu, bst, policy, nlg]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='ADVISER 2.0 Dialog System')
    parser.add_argument('--debug', action='store_true', help="enable debug mode")
    parser.add_argument('--log_file', choices=['info', 'errors', 'none'], 
                        default="none",
                        help="specify file log level")
    parser.add_argument('--log', choices=['info', 'errors', 'none'], 
                        default="results",
                        help="specify console log level")
    parser.add_argument('--cuda', action='store_true', help="enable cuda (currently only for asr/tts)")
    parser.add_argument('--privacy', action='store_true',
                        help="enable random mutations of the recorded voice to mask speaker identity", default=False)
    
    args = parser.parse_args()

    domains = []
    services = []

    # setup logger
    file_log_lvl = LogLevel[args.log_file.upper()]
    log_lvl = LogLevel[args.log.upper()]
    conversation_log_dir = './conversation_logs'
    logger = DiasysLogger(file_log_lvl=file_log_lvl,
                          console_log_lvl=log_lvl,
                          logfile_folder=conversation_log_dir,
                          logfile_basename="full_log")
    # logger = my_logger
    # load domain specific services
    i_domain, i_services = load_domain(logger=logger)
    domains.append(i_domain)
    services.extend(i_services)
    services.extend(load_console())

    # setup dialog system
    services.append(DomainTracker(domains=domains))
    logger.debug("hi")
    debug_logger = logger if args.debug else None
    #ds = DialogSystem(services=services, debug_logger=debug_logger)
    ds = DialogSystem(services=services, debug_logger=logger)
    error_free = ds.is_error_free_messaging_pipeline()
    if not error_free:
        ds.print_inconsistencies()
    if args.debug:
        ds.draw_system_graph()


    try:
        ds.run_dialog({'gen_user_utterance': ""})
        ds.shutdown()
    except:
        import traceback
        print("##### EXCEPTION #####")
        traceback.print_exc()