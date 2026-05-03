from sqlalchemy import create_engine, text
import requests
import pandas as pd
import os
from dotenv import load_dotenv

load_dotenv()
conn_string = os.getenv("CONN_STRING")

def fetch_pbp(game_id: str):
    response = requests.get(f"https://lscluster.hockeytech.com/feed/index.php?feed=gc&tab=pxpverbose&game_id={game_id}&key=446521baf8c38984&client_code=pwhl")
    return response.json()["GC"]["Pxpverbose"]

def fetch_schedule(season_id: str):
    response = requests.get(f"https://lscluster.hockeytech.com/feed/?feed=modulekit&view=schedule&season_id={season_id}&key=446521baf8c38984&client_code=pwhl")
    return response.json()["SiteKit"]["Schedule"]

def fetch_seasons():
    response = requests.get(f"https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&view=seasons&key=446521baf8c38984&client_code=pwhl")
    return response.json()['SiteKit']['Seasons']

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

def parse_game(game_id: str, home_id: str, visiting_id: str, use_shootouts: bool = True):
    print(f"Parsing game {game_id}")
    events = fetch_pbp(game_id)

    events_out = []
    assists_out = []
    plusminus_out = []
    states_out = []
    teamstates_out = []
    
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
    if events[-1]["event"] == "shootout":
        max_time = 3900
    if events[-1]["event"] == "goal":
        max_time = max((event['event_time'] for event in events), default=0)
    if events[-1]["event"] == "shot":
        if event["game_goal_id"] != "":
            max_time = max((event['event_time'] for event in events), default=0)

    # game state handling
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
        
        home_skaters = 5 - (len(home_penalties[0]) > 0) - (len(home_penalties[1]) > 0) + (home_goalie is None)
        visiting_skaters = 5 - (len(visiting_penalties[0]) > 0) - (len(visiting_penalties[1]) > 0) + (visiting_goalie is None)
        if use_shootouts and current_time > 3600:
            home_skaters = 3 + (len(visiting_penalties[0]) > 0) + (len(visiting_penalties[1]) > 0) + (home_goalie is None) + ot_ppexp_nowhistle
            visiting_skaters = 3 + (len(home_penalties[0]) > 0) + (len(home_penalties[1]) > 0) + (visiting_goalie is None) + ot_ppexp_nowhistle
        
        if current_time == 0:
            state = (home_skaters - 1, visiting_skaters - 1, False, False)
        else:
            state = (home_skaters, visiting_skaters, home_goalie is None, visiting_goalie is None)
        if state != current_state:
            print(f"{current_time}: {state}")
            if current_time != 0:
                states_out.append({
                    'state_id': f"{game_id}{current_start:05}",
                    'game_id': game_id,
                    'start_time': current_start,
                    'end_time': current_time,
                })
                teamstates_out.append({
                    'state_id': f"{game_id}{current_start:05}",
                    'team_id': home_id,
                    'skaters': current_state[0],
                    'goalie_pulled': current_state[2],
                    'opp_skaters': current_state[1],
                    'opp_goalie_pulled': current_state[3],
                })
                teamstates_out.append({
                    'state_id': f"{game_id}{current_start:05}",
                    'team_id': visiting_id,
                    'skaters': current_state[1],
                    'goalie_pulled': current_state[3],
                    'opp_skaters': current_state[0],
                    'opp_goalie_pulled': current_state[2],
                })
            current_state = state
            current_start = current_time
        
        # Process events at this second
        for event in events[events_processed:]:
            if event['event_time'] > current_time:
                break
            else:
                event_id = int(f"{game_id}{events_processed:04}")
                event_type = event["event"]
                event_team = event.get("team_id", event.get("team", -1))
                raw_time = event.get("time_formatted", event.get("time", event.get("time_off_formatted", "-1:-1")))
                period = event.get("period_id", event.get("period", -1))
                
                # goalie change
                if event_type == "goalie_change":
                    if not event["goalie_in_id"]:
                        goalie_in = None
                    elif event["goalie_in_id"] == '0':
                        goalie_in = None
                    else:
                        goalie_in = event["goalie_in_id"]
                    if event_team == home_id:
                        home_goalie = goalie_in
                    else:
                        visiting_goalie = goalie_in

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

                # shot on goal incl. goals
                elif event_type == "shot":
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

                # faceoff
                elif event_type == "faceoff":
                    ot_ppexp_nowhistle = 0

                # compile tables
                if event_type in ["faceoff", "hit", "blocked_shot"]:
                    events_out.append({"event_id": event_id, 
                                       "game_id": game_id, 
                                       "event_type": event_type, 
                                       "event_time": current_time, 
                                       "x": 100 - float(event["x_location"])/3, 
                                       "y": 42.5 - float(event["y_location"])*85/300,
                                       "shot_type": None, 
                                       "player_id": None, 
                                       "goalie_id": None,
                                       "is_goal": None,
                                       "team_id": event.get('team_id', None),
                                       "goalie_team_id":None,
                                       "xg": None,
                                       "penalty_class": None,
                                       "pim": None})
                if event_type == "shot":
                    goalie_id = event["goalie"]["player_id"]
                    if not goalie_id or goalie_id == '0': 
                        goalie_id = None
                        xg = 1.
                    else:
                        xg = None

                    events_out.append({"event_id": event_id, 
                                       "game_id": game_id, 
                                       "event_type": event_type, 
                                       "event_time": current_time, 
                                       "x": float(event["x_location"])/3 - 100, 
                                       "y": float(event["y_location"])*85/300 - 42.5,
                                       "shot_type": event["shot_type"], 
                                       "player_id": event["player"]["player_id"], 
                                       "goalie_id": goalie_id,
                                       "is_goal": event["game_goal_id"] != "",
                                       "team_id": event["team_id"],
                                       "goalie_team_id": event["goalie"]["team_id"],
                                       "xg": xg,
                                       "penalty_class": None,
                                       "pim": None})
                if event_type == "goal":
                    event_id = int(f"{game_id}{(events_processed - 1):04}")
                    if event["assist1_player_id"]:
                        assists_out.append({"event_id": event_id, "player_id": event["assist1_player_id"], "primary_assist": True})
                    if event["assist2_player_id"]:
                        assists_out.append({"event_id": event_id, "player_id": event["assist2_player_id"], "primary_assist": False})
                    for player in event["plus"]:
                        plusminus_out.append({"event_id": event_id, "player_id": player["player_id"], "plus": True})
                    for player in event["minus"]:
                        plusminus_out.append({"event_id": event_id, "player_id": player["player_id"], "plus": False})
                if event_type == "penalty":
                    if event['player_id']:
                        event_id = event_id
                        events_out.append({
                            "event_id": event_id,
                            "game_id": game_id,
                            "event_type": event_type, 
                            "event_time": current_time, 
                            "x": None, 
                            "y": None,
                            "shot_type": None, 
                            "player_id": event["player_id"], 
                            "goalie_id": None,
                            "is_goal": None,
                            "team_id": event["player_penalized_info"]["team_id"],
                            "goalie_team_id": None,
                            "xg": None,
                            "penalty_class": event['penalty_class_id'],
                            "pim": int(float(event['minutes']))
                        })
                    if event_type == "penaltyshot":
                        goalie_id = event["goalie"]["player_id"]
                        events_out.append({"event_id": event_id, 
                                       "game_id": game_id, 
                                       "event_type": event_type, 
                                       "event_time": current_time, 
                                       "x": None, 
                                       "y": None,
                                       "shot_type": "penaltyshot", 
                                       "player_id": event["player"]["player_id"], 
                                       "goalie_id": goalie_id,
                                       "is_goal": event["result"] == "goal",
                                       "team_id": event["team_id"],
                                       "goalie_team_id": event["goalie"]["team_id"],
                                       "xg": 0.3,
                                       "penalty_class": None,
                                       "pim": None})
                # move to next event and restart loop
                events_processed += 1
    
    # record final game state
    states_out.append({
        'state_id': f"{game_id}{current_start:05}",
        'game_id': game_id,
        'start_time': current_start,
        'end_time': max_time+1,
    })  
    teamstates_out.append({
        'state_id': f"{game_id}{current_start:05}",
        'team_id': home_id,
        'skaters': current_state[0],
        'goalie_pulled': current_state[2],
        'opp_skaters': current_state[1],
        'opp_goalie_pulled': current_state[3],
    })
    teamstates_out.append({
        'state_id': f"{game_id}{current_start:05}",
        'team_id': visiting_id,
        'skaters': current_state[1],
        'goalie_pulled': current_state[3],
        'opp_skaters': current_state[0],
        'opp_goalie_pulled': current_state[2],
    })

    for state in teamstates_out: print(state)
    

    '''# push to postgres
    engine = create_engine(conn_string)
    events_out = pd.DataFrame(events_out)
    events_out.to_sql('events', engine, if_exists='append', index=False)
    assists_out = pd.DataFrame(assists_out)
    assists_out.to_sql('assists', engine, if_exists='append', index=False)
    plusminus_out = pd.DataFrame(plusminus_out)
    plusminus_out.to_sql('plusminus', engine, if_exists='append', index=False)
    states_out = pd.DataFrame(states_out)
    states_out.to_sql('states', engine, if_exists='append', index=False)
    teamstates_out = pd.DataFrame(teamstates_out)
    teamstates_out.to_sql('teamstates', engine, if_exists='append', index=False)'''

def parse_season(season_id: str, replace=True):
    print(f"Parsing season {season_id}")
    schedule = fetch_schedule(season_id)
    schedule = [game for game in schedule if game['final'] == '1']

    games_out = []

    engine = create_engine(conn_string)
    games_in_db = []
    with engine.connect() as conn:
        result = conn.execute(text("SELECT game_id FROM games"))
        for row in result:
            games_in_db.append(row[0])

    for game in schedule:
        home_id = game["home_team"]
        visiting_id = game["visiting_team"]
        game_id = game["game_id"]
        date = game["date_played"]
        use_shootouts = game["use_shootouts"] == '1'

        if int(game_id) not in games_in_db:
            parse_game(game_id, home_id, visiting_id, use_shootouts)

            games_out.append({
                'game_id': game_id,
                'home_id': home_id,
                'visiting_id': visiting_id,
                'date': date,
                'season_id': season_id,
                'use_shootouts': use_shootouts
            })
        
    engine = create_engine(conn_string)
    if games_out:
        games_out = pd.DataFrame(games_out)
        games_out.to_sql('games', engine, if_exists='append', index=False)

def parse_all():
    seasons = fetch_seasons()
    engine = create_engine(conn_string)
    seasons_in_db = []
    with engine.connect() as conn:
        result = conn.execute(text("SELECT season_id FROM seasons"))
        for row in result:
            seasons_in_db.append(row[0])

    for season in seasons:
        season_id = season['season_id']
        if season['playoff'] == '1':
            season_type = 2
        elif season['career'] == '1':
            season_type = 1
        else:
            season_type = 0
        season_name = season['season_name']
        parse_season(season_id)

        if int(season_id) not in seasons_in_db:
            engine = create_engine(conn_string)
            season = pd.DataFrame([{"season_id": season_id, "season_type": season_type, "season_name": season_name}])
            season.to_sql('seasons', engine, if_exists='append', index=False)

if __name__ == "__main__":
    parse_game('338', '1', '5')