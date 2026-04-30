import requests
import pandas as pd
from fetch import fetch_seasons
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()
conn_string = os.getenv("CONN_STRING")

def fetch_players(team_id, season_id):
    request = requests.get(f"https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&view=roster&team_id={team_id}&season_id={season_id}&key=446521baf8c38984&client_code=pwhl")
    return request.json()['SiteKit']['Roster']

def fetch_teams(season_id):
    request = requests.get(f"https://lscluster.hockeytech.com/feed/index.php?feed=modulekit&view=teamsbyseason&season_id={season_id}&key=446521baf8c38984&client_code=pwhl")
    return request.json()['SiteKit']['Teamsbyseason']

def record_players(team_id, season_id, df):
    players = fetch_players(team_id, season_id)
    for player in players:
        if type(player) == dict:
            player_id = player['playerId']
            if not (df['player_id'] == player_id).any():
                new_row = pd.DataFrame([{
                                        "player_id": int(player_id), 
                                         "first_name": player['first_name'], 
                                         "last_name": player["last_name"], 
                                         "player_image": player['player_image'], 
                                         "shoots": player['shoots'],
                                         "team_id": player['latest_team_id']
                                         }])
                df = pd.concat([df, new_row], ignore_index=True)
    return df

def update_biographical():
    df = pd.DataFrame(columns=['player_id', 'first_name', 'last_name', 'player_image', 'shoots', 'team_id'])
    for season in fetch_seasons():
        season_id = season['season_id']
        for team in fetch_teams(season_id):
            team_id = team['id']
            print(f"fetching team {team_id} for season {season_id}")
            df = record_players(team_id, season_id, df)

    engine = create_engine(conn_string)
    df.to_sql('biographical', engine, if_exists='replace', index=False)


if __name__ == "__main__":
    update_biographical()