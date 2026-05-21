import numpy as np
import pandas as pd

from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from xgboost import XGBClassifier, plot_importance

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

import matplotlib.pyplot as plt

num_outerfolds = 5

load_dotenv()
conn_string = os.getenv("CONN_STRING")

def seasonal_auc_scorer(estimator, X, y):
    seasons = X['season_id']
    y_pred = estimator.predict_proba(X)[:, 1]
    return auc_with_calibration(y, y_pred, seasons=seasons)

def auc_with_calibration(y_true, y_pred, seasons=None):
    if seasons is not None:
        calibrations = []
        seasons = [int((s-1)/3) for s in seasons]
        for season in np.unique(seasons):
            mask = (seasons == season)
            calibrations.append(abs(1 - np.sum(y_pred[mask])/np.sum(y_true[mask])))
    else:
        calibrations = [abs(1 - np.sum(y_pred)/np.sum(y_true))]

    if all(calibration < 0.03 for calibration in calibrations):
        return roc_auc_score(y_true, y_pred)
    else:
        return 0
    
def fetch_data(nullonly = False, season = None, fetch_season_id = True):
    engine = create_engine(conn_string)
    query = ""
    with open('Scripts/xg-query.txt', 'r') as file:
        query = file.read()

    if nullonly: 
        query += " AND xg IS NULL"
    else:
        query += " AND games.season_id != 2"

    df = pd.read_sql_query(text(query), engine)

    categoricals = [
        'shot_type',
        'prev_type',
        'game_state'
    ]
    df[categoricals] = df[categoricals].astype('category')

    booleans = [
        'crossed_royal_road',
        'off_hand',
        'from_glove_side'
    ]
    df[booleans] = df[booleans].astype('boolean')

    if season:
        df = df[df.season_id == season]

    if not fetch_season_id:
        df = df.drop('season_id', axis=1)

    return df.drop(['is_goal', 'event_id'], axis=1), df.is_goal, df.event_id


def retrain_model(season = None):
    if season:
        print(f"Retraining model for season {season}...")

    X, y, ids = fetch_data(season=season)

    # Define the hyperparameter grid for XGBoost
    param_grid = {
        'clf__max_depth': [3, 5, 7],
        'clf__learning_rate': [0.1, 0.01, 0.001],
        'clf__n_estimators': [50, 100, 200]
    }
    
    # Create the outer and inner cross-validation objects
    outer_cv = StratifiedKFold(n_splits=num_outerfolds, shuffle=True, random_state=42)
    inner_cv = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)

    # Perform nested cross-validation
    outer_scores = []
    
    output = pd.DataFrame()
    calibration = [0, 0]

    for n, (train_idx, test_idx) in enumerate(outer_cv.split(X, y)):
        print(f"Training model {n}")

        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        ids_test = ids[test_idx]

        pipeline = Pipeline([
            ('drop_season_id', FunctionTransformer(lambda X: X.drop(columns=['season_id']), validate=False)),
            ('clf', XGBClassifier(random_state=42, objective='binary:logistic', tree_method='hist', enable_categorical=True))
        ])

        grid_search = GridSearchCV(estimator=pipeline, param_grid=param_grid, cv=inner_cv, scoring=seasonal_auc_scorer)
        grid_search.fit(X_train, y_train)

        # Train the model with the best hyperparameters on the outer training fold
        best_model = grid_search.best_estimator_
        best_model.fit(X_train, y_train)

        # Evaluate the model on the outer validation fold
        y_pred = best_model.predict_proba(X_test)[:, 1]
        score = roc_auc_score(y_test, y_pred)
        outer_scores.append(score)

        calibration[0] += np.sum(y_pred)
        calibration[1] += np.sum(y_test)

        if season:
            best_model.named_steps['clf'].save_model(f'model_output/s_{season}_model_{n}.json')
            df = pd.DataFrame(zip(ids_test, y_pred))
            output = pd.concat([output, df])
        else:
            best_model.named_steps['clf'].save_model(f'model_output/model_{n}.json')
            df = pd.DataFrame(zip(ids_test, y_pred))
            output = pd.concat([output, df])

    print(f"Nested cross-validation scores: {outer_scores}")
    print(f"Mean score: {np.mean(outer_scores):.3f} +/- {np.std(outer_scores):.3f}")
    print(f"Model calibration: {calibration[0] / calibration[1]}")

    if season:
        output.to_csv(f'model_output/s_{season}_output.csv')
    else:
        output.to_csv('model_output/output.csv')

def push_results():
    df = pd.read_csv('model_output/output.csv')
    engine = create_engine(conn_string)

    df.to_sql('temp_staging', engine, if_exists='replace', index=False)

    with engine.begin() as conn:
        conn.execute(text(
            '''
            UPDATE events
            SET xg = temp_staging."1"
            FROM temp_staging
            WHERE events.event_id = temp_staging."0";
            UPDATE events
            SET xg = NULL
            WHERE events.event_id NOT IN (SELECT "0" FROM temp_staging) 
                AND xg < 1
                AND events.event_type = 'shot';
            '''
        ))
        conn.execute(text("DROP TABLE temp_staging"))

def calc_new_xg():
    models = []
    for i in range(num_outerfolds):
        model = XGBClassifier()
        model.load_model(f'model_output/model_{i}.json')
        models.append(model)

    X, y, ids = fetch_data(nullonly=True, fetch_season_id=False)

    output = pd.DataFrame({'event_id': ids})

    if len(X):
        for i, model in enumerate(models):
            output[f'model_{i}'] = model.predict_proba(X)[:, 1]

    output['consensus'] = output.drop('event_id', axis=1).mean(axis=1)
    output = output[['event_id', 'consensus']]
    output['event_id'] = output['event_id'].astype(int)

    engine = create_engine(conn_string)
    output.to_sql('temp', engine, if_exists='replace', index=False)
    with engine.begin() as conn:
        query = """
            UPDATE events
            SET xg = temp.consensus
            FROM temp
            WHERE events.event_id = temp.event_id
        """
        conn.execute(text(query))

def push_calc_eval():
    push_results()
    calc_new_xg()
    engine = create_engine(conn_string)
    
    query = """
        SELECT event_id, xg, is_goal
        FROM events
        WHERE event_type = 'shot' AND xg IS NOT NULL AND xg < 1
    """
    df = pd.read_sql_query(text(query), engine)
    print(f"Model AUC-ROC: {roc_auc_score(df.is_goal, df.xg):.3f}")
    print(f"Model Calibration: {df.is_goal.sum() / df.xg.sum():.3f}")

def eval_season(season: int):
    engine = create_engine(conn_string)
    query = f"""
        SELECT event_id, xg, is_goal
        FROM events
        JOIN games ON events.game_id = games.game_id
        WHERE event_type = 'shot' AND xg IS NOT NULL AND season_id = {season} AND xg < 1
    """
    df = pd.read_sql_query(text(query), engine)
    print(f"Season {season} evaluation:")
    print(f"Model AUC-ROC: {roc_auc_score(df.is_goal, df.xg):.3f}")
    print(f"Model Calibration: {df.is_goal.sum() / df.xg.sum():.3f}")

if __name__ == "__main__":
    retrain_model()
    push_calc_eval()
    for season in [1, 5, 8]:
        eval_season(season)