from random import shuffle

class TellerCoursePicker:
    """ 
        Use random greedy + brute-force to search for solutions that
        meet the constraints.

        All candidate courses already fulfilled two constraints:
            - semester
            - credits <= total_credits
        Other constraints that need to be met:
            - formats
            - fields
            - sum(credits) == total_credits    

        Data structures description:
            constraints related:
                total_credits: int, used to terminate the searching procedure
                formats: Set, used to select courses that has the teaching format
                fields: Set, used to select courses in this fields
                user_schedules: List of str, to avoid conflicts
            algorithm aux structures:
                day2min: Set, map str that represents day and time to an int
                    used to detect whether time conflicts exist
                solution: List[List[str](name of courses)]
            for output: (info that NLG needs to show)
                time_slot: map a course name to time, NLG need to show this
                    e.g. time_slot["dialog system"] = "Wed. 9:00-11:30"
                name2credit: map a course name to its credit
    """
    def __init__(self) -> None:
        self.clear()
        self.day2min = self._build_day2min_mapper()

    def clear(self):
        """
            initialize all the data structures
        """
        self.total_credits = 100
        self.candidates = []
        self.solution = []
        self.time_slots = {} # used to map name to time
        self.name2credit = {} # map name to credits
        self.user_schedules = []
        self.formats = set()
        self.fields = set()


    # some aux functions to set the values
    def update_user_schedules(self, schedules):
        self.user_schedules = schedules

    
    def update_total_credits(self, total_credits):
        self.total_credits = int(total_credits)


    def update_formats(self, formats):
        self.formats = set(formats)
    
    
    def update_fields(self, fields):
        self.fields = set(fields)


    def _random_greedy_select(self, candidates, target_credits):
        """
            A greedy algorithm to approximate the target_credits using
            courses from candidates.

            Greedy part:
                select the courses from start to end until the 
                sum of credits will exceed the target credits if we 
                add the next course 
            Problem:
                the order of courses matter. It fails if the first 
                one exceeds the target_credits.
            Solution:
                Shuffle the candidates 10 times, choose the one with 
                the highest score.

            Args:
                candidate: List[dict], list of courses
                target_credits: int
            
            Return:
                best_credits: int
                best_names: List[str], solution, a list of course names
        """
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


    def _search_for_preference(self, names, candidates, target_credits):
        """
            Given a set of course names that meet some constraints, 
            generate a solution that has the closest total credits to 
            total_credits

            Args:
                names: Set(str), a set of courses that meet some constraints.
                    e.g., all courses that have the both the prefered formats 
                          and fields
                          or all courses that have at least one of user's 
                          preferred teaching format or study field.
                candidate: List(Dict), the current candidate courses 
                target_credit: int, the target credit it tries to approximate
            
            Return:
                credit: int, the actual total credits of the solution
                solution: List[str], a list of course names
        """
        # if the user doesn't provide her preferences, don't do search_for_preference
        if len(names) == 0:
            return 0, set() 
        # filter by name
        new_candidates = [course for course in candidates if course["Name"] in names]
        candidates = new_candidates
        # use a random and greedy algorithm
        return self._random_greedy_select(candidates, target_credits)


    def _filter_courses(self, slot, constraints):
        """
            Filter the original candidates with the Format or 
            Field constraints.

            Args:
                slot: str, "Format" or "Field"
                constraints: List[str], user's preferred formats or 
                            fields

            Returns:
                Set[str]: a set of course names
        """
        if len(constraints) == 0:
            return set()

        ret = []
        for course in self.candidates:
            for target in constraints:
                if target.lower() in course[slot].lower():
                    ret.append(course["Name"])
                    break
        return set(ret)


    def _select_one_solution(self, candidates, field_candidates, format_candidates):
        """
            The whole algorithm to select a solution that
            - sum(credits of solution) == total_credits
            - meets the sms constriants
            - tries to select many courses that meet the format and field constraints
                more specifically
                - has many courses that meet both
                - has many courses that meet at least one constraints
        """
        # stage 1: select the courses that meet both requirements, approximate half total credits
        inter_set = list(field_candidates&format_candidates)
        inter_credits, inter_set_solution = self._search_for_preference(inter_set, candidates, max(3, int(0.5 * self.total_credits)))
        
        # stage 2: select the course that meet either requirements, approximate half total credits
        union_set = (field_candidates| format_candidates) - inter_set_solution
        union_credits, union_set_solution = self._search_for_preference(union_set, candidates, max(0, self.total_credits - inter_credits))

        # check any remain credit left cuz the above two 
        # are just approximating the score
        remain_credits = self.total_credits - inter_credits - union_credits
        
        if remain_credits == 0:
            self.solution = list(inter_set_solution) + list(union_set_solution)
            return self.solution

        # have some credits left 
        # stage 3: fill the credit gap by selecting other courses using brute force algorithm
        self.solution = []
        self.stack = []
        self.candidates = []

        # remove the courses that already exist in the above solutions 
        # from the candidate
        for course in candidates:
            course_name = course["Name"]
            if course_name in inter_set_solution or course_name in union_set_solution:
                continue
            self.candidates.append(course)

        # start brute-forcing 
        status = self._brute_force_meet_total_credits(0, 0, remain_credits)
        if status:
            # successfully find a complete solution
            self.solution = list(inter_set_solution) + list(union_set_solution) + self.solution
        else:
            self.solution = []
        return self.solution

    
    def select_courses(self, raw_candidates):
        """
            Prepare all data and aux data structures, 
            Run the course selection algorithm 3 time and return at 
            most 3 solutions. (some runs will fail because the 
            greedy algoirithm doesn't gaurantee to find a solution, it
            is greatly influenced by the course order. For more details, 
            please refer to _random_greedy_select)
        """
        self.candidates = raw_candidates
        
        # change time from str to minutes for easy comparison
        for candidate in self.candidates:
            candidate["Dates"] = self._change_time_format(candidate)
            self.name2credit[candidate["Name"]] = candidate["Credit"]
            candidate["Credit"] = int(candidate["Credit"])
        if len(self.user_schedules) > 0:
            self.user_schedules = self._change_time_format({
                "Name": "User",
                "Dates": ';'.join(self.user_schedules)
            })
        
        # remove candidates that go conflict with user's personal schedule
        self._remove_user_conflicts()

        # prepare time conflict graph for time conflict fast check
        # TODO: has memory redundacy, e.g., has both key i+j and j+i 
        self.time_conflict_graph = self._build_time_conflict_relation_graph()

        # the given candidates only meet the "sms" and "credit" constraints
        # further filter the candidate with "field" and "format" constraints    
        field_candidates = self._filter_courses("Field", self.fields)
        format_candidates = self._filter_courses("Format", self.formats)

        # 3 trials
        different_solutions = []
        for _ in range(3):
            shuffle(self.candidates)
            solution = self._select_one_solution(self.candidates, field_candidates, format_candidates)
            if len(solution) == 0:
                # remove the failed solution
                continue
            different_solutions.append(solution)
        
        if len(different_solutions) == 0:
            return []
        
        # unique solutions
        different_solutions = [list(x) for x in set(tuple(x) for x in different_solutions)]
        
        if len(different_solutions) == 1 and len(different_solutions[0]) == 0:
            return []

        # add the string format time and credit back because
        # NLG need to present them together with course names 
        for sol in different_solutions:
            for i in range(len(sol)):
                sol[i] = (sol[i], self.time_slots[sol[i]], self.name2credit[sol[i]])
        return different_solutions


    def _remove_user_conflicts(self):
        new_candidates = []
        for candidate in self.candidates:
            if self._has_overlap(candidate["Dates"], self.user_schedules):
                continue
            new_candidates.append(candidate)
        self.candidates = new_candidates


    def _has_overlap(self, times_a, times_b):
        """ 
            check if two given time range overlap or not

            Args:
            times_a: (int, int)
                the start time and end time of a course
            times_b: (int, int)
                the start time and end time of a course

            Returns:
            true: has time conflicts 
            false: no time conflicts
            
        """
        for a in times_a:
            for b in times_b:
                overlap = max(0, min(a[1], b[1]) - max(a[0], b[0]))
                if overlap > 0:
                    return True
        return False


    def _build_time_conflict_relation_graph(self):
        """
            build a dictionary to fast check whether two given
            courses have time conflicts

            e.g., courses are "dialog system" and "team lab", then
            dict["dialog system+team lab"] is True if they have 
            conflicts

            Returns:
                dict[str]:bool
        """
        has_conflicts = {}
        for course_i in self.candidates:
            i = course_i["Name"]
            for course_j in self.candidates:
                j = course_j["Name"]
                if i == j: continue
                has_conflicts[i+"+"+j] = self._has_overlap(course_i["Dates"], course_j["Dates"])
        return has_conflicts


    def _build_day2min_mapper(self):
        """
            Create a mapper to map day to a int offset. 
            Because later we need to map "Day. hh:mm-hh:mm" to int 
            for easy time comparison.
        """
        days = ["mon", "tue", "wed", "thur", "fri", "sat", "sun"]
        cur_offset = 0
        day2min = {}
        one_day = 24*3600

        for day in days:
            day2min[day] = cur_offset 
            cur_offset += one_day
        return day2min


    def _change_time_format(self, candidate):
        """ 
            Change time format to minutes(the number of minutes that
            has passed in a week)
            e.g., "tue. 9:00-11:00"
            int(tue. 9:00-11:30) 
                start time: 24*60*60(one day)+ 9*60
                end time: 24*60*60 + 11*60 + 30
            
            Args:
                candidate: List[dict] list of courses
                time_slot_in_minutes: Dict[str] = [str day, str duration, int start time, int end time]
                    e.g., dict["dialog system"] = ["tue", "9:00-11:30", 86940, 87090]
        """
        name = candidate["Name"]
        dates = candidate["Dates"].split(";")
        time_slot_in_minutes = []
        for date in dates:
            date = date.strip().lower()
            day, duration = date.split('.')
            day, duration = day.strip(), duration.strip()
            min_offset = self.day2min[day]
            start_time, end_time = duration.split('-')
            start_time, end_time = self._clock2min(start_time), self._clock2min(end_time)
            start_time += min_offset
            end_time += min_offset
            time_slot_in_minutes.append((start_time, end_time))
            
            if name not in self.time_slots: 
                self.time_slots[name] = []
            self.time_slots[name].append((day, duration, start_time, end_time))
        return time_slot_in_minutes


    def _clock2min(self, clock_time):
        """
        Map "hh:mm" to int.
        """
        clock_time = clock_time.strip()
        hh, mm = clock_time.split(":")
        hh, mm = int(hh.strip()), int(mm.strip())
        return hh*60 + mm


    def _has_time_conflicts_for_random(self, candidates, course_id: int):
        """
            Time conflict checking function used in random_greedy_search
            check whether a given course has conficts with all the other
            courses in the temp solution.

            Args:
                course_id: the index of the given course
                candidates: List[dict], the temp solutions
        """
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
        """
            Time conflict checking function used in brute-force algorithm.
            Check whether a given course has time conflicts with courses
            in the stack(the brute-force is a recursive algorithm, and use
            stack to keep track of the latest choices).

            Args:
                course_id: the index of the given course
        """
        cur_name = self.candidates[course_id]["Name"]
        for pre in self.stack:
            pre_name = self.candidates[pre]["Name"]
            if pre_name == cur_name:
                continue 
            name_bind = pre_name + "+" + cur_name 

            # the following statement should always be false
            if name_bind not in self.time_conflict_graph:
                print("error! key not found", name_bind)
                for k in self.time_conflict_graph:
                    print(f"key in graph: {k}")
                return False
                
            if self.time_conflict_graph[name_bind]:
                return True
        return False

    
    def _brute_force_meet_total_credits(self, cur_credits = 0, cur_id = 0, total_credits = 0):
        """
            A recursive algorithm to enumerate all possible course combinations.
            Theorectically it is very inefficient because the runtime is exponential.
            In practice it's fast because
                - prune the searching process using constraints.
                - there is a greedy algorithm to select most courses when there are format and field constraints.
        """
        # TODO: need to maintain a dependency graph, telling the module which courses are choosable
        self.stack.append(cur_id)
        if cur_id >= len(self.candidates):
            self.stack.pop()
            return False

        if self._has_time_conflicts(cur_id):
            self.stack.pop()
            return False

        # option 1: choose myself and meet the credits
        new_credit = cur_credits + int(self.candidates[cur_id]['Credit'])
        if new_credit == total_credits:
            self.solution.append(self.candidates[cur_id]['Name'])
            self.stack.pop()
            return True
        # option 1: choose myself and need to explore more 
        elif self._brute_force_meet_total_credits(new_credit, cur_id+1, total_credits):
            self.solution.append(self.candidates[cur_id]['Name'])
            self.stack.pop()
            return True
        
        # option 2: don't choose myself
        self.stack.pop()
        if self._brute_force_meet_total_credits(cur_credits, cur_id+1, total_credits):
            return True
        else:
            return False