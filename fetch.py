import duckdb
import requests
import pandas as pd
import json

def fetch_pbp(game_id: str):
    response = requests.get(f"https://lscluster.hockeytech.com/feed/index.php?feed=gc&tab=pxpverbose&game_id={game_id}&key=446521baf8c38984&client_code=pwhl")
    return response.json()["GC"]["Pxpverbose"]

def fetch_schedule(season_id: str):
    response = requests.get(f"https://lscluster.hockeytech.com/feed/?feed=modulekit&view=schedule&season_id={season_id}&key=446521baf8c38984&client_code=pwhl")
    return response.json()["SiteKit"]["Schedule"]

def time_to_seconds(time_str: str, period: str) -> int:
    minutes, seconds = map(float, time_str.split(':'))
    period = int(period)
    return int((period - 1) * 60 * 20 + minutes * 60 + seconds)

def penalty_expiration(penalties, current_time):
    state = (len(penalties[0]), len(penalties[1]), len(penalties[2]))
    penalties[0] = [pen for pen in penalties[0] if current_time <= pen['end']]
    if penalties[1]:
        penalties[1] = [pen for pen in penalties[1] if current_time <= pen['end']]
    if penalties[2]:
        if not penalties[0]:
            penalties[0].append(penalties[2].pop(0))
    if penalties[2]:
        if not penalties[1]:
            penalties[1].append(penalties[2].pop(0))
    if state != (len(penalties[0]), len(penalties[1]), len(penalties[2])): 
        return 1
    else:
        return 0

def penalty_assignment(penalties, penalty):
    serving_player = penalty["served_by"]
    pen_length = penalty["length"]

    if not penalties[0] and not penalties[1]:
        penalties[0].append(penalty)
    elif [pen for pen in penalties[0] if pen["served_by"] == serving_player]:
        penalty["start"] = penalties[0][-1]["end"]
        penalty["end"] = penalties[0][-1]["end"] + pen_length
        penalties[0].append(penalty)
    elif not penalties[1]:
        penalties[1].append(penalty)
    elif [pen for pen in penalties[1] if pen["served_by"] == serving_player]:
        penalty["start"] = penalties[1][-1]["end"]
        penalty["end"] = penalties[1][-1]["end"] + pen_length
        penalties[1].append(penalty)
    else:
        penalties[2].append(penalty)

def penalty_goal_scored(penalties):
    if penalties[0] and penalties[1]:
        if penalties[0][0]["end"] <= penalties[1][0]["end"] and penalties[0][0]["class"] != "3":
            early_exp(penalties[0])
        elif penalties[1][0]["class"] != "3":
            early_exp(penalties[1])
    elif penalties[0] and penalties[0][0]["class"] != "3":
        early_exp(penalties[0])
    elif penalties[1] and penalties[1][0]["class"] != "3":
        early_exp(penalties[1])
    if penalties[2]:
        if not penalties[0]:
            penalties[0].append(penalties[2].pop(0))
    if penalties[2]:
        if not penalties[1]:
            penalties[1].append(penalties[2].pop(0))

def early_exp(penalties):
    start = penalties[0]["end"]
    penalties.pop(0)
    if(penalties):
        for i, pen in enumerate(penalties):
            penalties[i]["start"] = start
            start = penalties[i]["end"]
            penalties[i]["end"] = penalties[i]["start"] + penalties[i]["length"]

def parse_game(game_id: str, home_id: str, use_shootouts: bool = True):
    # right now this just spits pbp data into console
    events = fetch_pbp(game_id)
    
    # TEST CODE 
    #events = None
    #with open('data.json', 'r') as file:
    #    events = json.load(file)
    
    # event times for iterating
    for event in events:
        raw_time = event.get("time_formatted", event.get("time", event.get("time_off_formatted", "-1:-1")))
        period = event.get("period_id", event.get("period", -1))
        event['event_time'] = time_to_seconds(raw_time, period)
    
    max_time = 3600
    print(events[-1]["event"])
    if events[-1]["event"] == "shootout":
        max_time = 3900
    if events[-1]["event"] == "goal":
        max_time = max((event['event_time'] for event in events), default=0)
    if events[-1]["event"] == "shot":
        if event["game_goal_id"] != "":
            max_time = max((event['event_time'] for event in events), default=0)

    # game state handling    
    states = []
    current_state = None
    current_start = 0
    
    home_goalie = None
    visiting_goalie = None
    score_state = 0
    # first active, second active, inactive
    home_penalties = [[], [], []]
    visiting_penalties = [[], [], []]

    ot_ppexp_nowhistle = 0
    
    events_processed = 0

    for current_time in range(max_time + 1):
        ot_ppexp_nowhistle += penalty_expiration(home_penalties, current_time)
        ot_ppexp_nowhistle += penalty_expiration(visiting_penalties, current_time)
        
        home_skaters = 5 - int(len(home_penalties[0]) > 0) - int(len(home_penalties[1]) > 0) + int(home_goalie is None)
        visiting_skaters = 5 - int(len(visiting_penalties[0]) > 0) - int(len(visiting_penalties[1]) > 0) + int(visiting_goalie is None)
        if use_shootouts and current_time > 3600:
            home_skaters = 3 + int(len(visiting_penalties[0]) > 0) + int(len(visiting_penalties[1]) > 0) + int(home_goalie is None) + ot_ppexp_nowhistle
            visiting_skaters = 3 + int(len(home_penalties[0]) > 0) + int(len(home_penalties[1]) > 0) + int(visiting_goalie is None) + ot_ppexp_nowhistle
        
        if current_time == 0:
            state = (home_skaters - 1, visiting_skaters - 1)
        else:
            state = (home_skaters, visiting_skaters)
        if state != current_state:
            if current_state is not None:
                states.append({
                    'state': current_state,
                    'start': max(current_start - 1, 0),
                    'end': current_time - 1
                })
            current_state = state
            current_start = current_time
        
        # Process events at this second
        for event in events[events_processed:]:
            if event['event_time'] >= current_time:
                break
            else:
                event_type = event["event"]
                event_team = event.get("team_id", event.get("team", -1))
                raw_time = event.get("time_formatted", event.get("time", event.get("time_off_formatted", "-1:-1")))
                period = event.get("period_id", event.get("period", -1))
                
                # goalie change
                if event_type == "goalie_change":
                    
                    if current_time == 0:
                        if event_team == home_id:
                            home_goalie = event["goalie_in_id"]
                            print(f"Home goalie: {home_goalie}")
                        else:
                            visiting_goalie = event["goalie_in_id"]
                            print(f"Visiting goalie: {visiting_goalie}")
                    else:
                        if event_team == home_id:
                            home_goalie = event["goalie_in_id"]
                            print(f"{period} - {raw_time}: Home goalie change: {home_goalie}")
                        else:
                            visiting_goalie = event["goalie_in_id"]
                            print(f"{period} - {raw_time}: Visiting goalie change: {visiting_goalie}")

                # penalty
                elif event_type == "penalty" and event["penalty_class_id"]  in ["1", "2", "3"]: #CHECK IF THESE IDs ARE CORRECT - 1: Minor / 2: ??? / 3: Major
                    if event["penalty_shot"] == "0":
                        pen_class = event["penalty_class_id"]
                        raw_length = event["minutes"]
                        pen_length = int(float(raw_length) * 60)
                        pen_team = event["team_id"]
                        serving_player = event["player_served_info"]["player_id"]
                        penalty = {"start": current_time, 
                                    "class": pen_class, 
                                    "length": pen_length,
                                    "end": current_time + pen_length, 
                                    "team": pen_team, 
                                    "served_by": serving_player
                                    }
                        
                        # penalty logic - properly assigning double minors, no more than one penalty at a time
                        # [0] first active [1] second active [2] inactive
                        if pen_team == home_id:
                            penalty_assignment(home_penalties, penalty)
                        else:
                            penalty_assignment(visiting_penalties, penalty)
                        print(f"{period} - {raw_time}: Team {pen_team} - {raw_length} minute penalty")

                # shot on goal incl. goals
                elif event_type == "shot":
                    shooter = event["player"]["player_id"]
                    goalie = event["goalie"]["player_id"]
                    is_goal = event["game_goal_id"] != ""

                    pp_sit = home_skaters - int(home_goalie is None) != visiting_skaters - int(visiting_goalie is None)
                    home_pp = home_skaters - int(home_goalie is None) > visiting_skaters - int(visiting_goalie is None)
                    
                    if is_goal:
                        score_state += int(event_team == home_id) - int(event_team != home_id)
                        if pp_sit:
                            if home_pp:
                                penalty_goal_scored(visiting_penalties)
                            else:
                                penalty_goal_scored(home_penalties)

                    shot_type = "goal" if is_goal else "shot"
                    print(f"{period} - {raw_time}: {shooter} {shot_type} on {goalie} at {home_skaters}v{visiting_skaters}")

                # faceoff
                elif event_type == "faceoff":
                    ot_ppexp_nowhistle = 0

                events_processed += 1
    
    if current_state is not None:
        states.append({
            'state': current_state,
            'start': current_start,
            'end': max_time
        })
    
    
    # Print the states
    for s in states:
        print(f"State {s['state']}: from {s['start']} to {s['end']}")

# Right now this does nothing don't call it
def parse_season(season_id: str):
    schedule = fetch_schedule(season_id)
    for game in schedule:
        home_team = game["home_team"]
        visiting_team = game["visiting_team"]
        game_id = game["game_id"]

if __name__ == "__main__":
    parse_game("199", "3", use_shootouts=False)