import numpy as np
import pandas as pd

from sklearn.metrics import make_scorer, roc_auc_score
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from xgboost import XGBClassifier

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

num_outerfolds = 5

load_dotenv()
conn_string = os.getenv("CONN_STRING")

def auc_with_calibration(y_true, y_pred):
    calibration = abs(1 - np.sum(y_pred)/np.sum(y_true))
    if calibration < 0.05:
        return roc_auc_score(y_true, y_pred)
    else:
        return 0
    
def fetch_data(nullonly = False):
    engine = create_engine(conn_string)
    query = ""
    with open('xg-query.txt', 'r') as file:
        query = file.read()
    if nullonly: query += " AND xg IS NULL"
    df = pd.read_sql_query(text(query), engine)

    categoricals = [
        'shot_type',
        'prev_type',
        'game_state'
    ]
    df[categoricals] = df[categoricals].astype('category')

    booleans = [
        'prev_event_same_team',
        'crossed_royal_road'
    ]
    df[booleans] = df[booleans].astype('boolean')

    return df.drop(['is_goal', 'event_id'], axis=1), df.is_goal, df.event_id

def retrain_model():
    scorer = make_scorer(auc_with_calibration)

    X, y, ids = fetch_data()

    # Define the hyperparameter grid for XGBoost
    param_grid = {
        'max_depth': [3, 5, 7],
        'learning_rate': [0.1, 0.01, 0.001],
        'n_estimators': [50, 100, 200]
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

        # Perform hyperparameter tuning with inner cross-validation
        model = XGBClassifier(random_state=42, objective='binary:logistic', tree_method='hist', enable_categorical=True)
        grid_search = GridSearchCV(estimator=model, param_grid=param_grid, cv=inner_cv, scoring=scorer)
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

        best_model.save_model(f'model_output/model_{n}.json')
        df = pd.DataFrame(zip(ids_test, y_pred))
        output = pd.concat([output, df])

    print(f"Nested cross-validation scores: {outer_scores}")
    print(f"Mean score: {np.mean(outer_scores):.3f} +/- {np.std(outer_scores):.3f}")
    print(f"Model calibration: {calibration[0] / calibration[1]}")

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
            WHERE events.event_id = temp_staging."0"
            '''
        ))
        conn.execute(text("DROP TABLE temp_staging"))

def calc_new_xg():
    models = []
    for i in range(num_outerfolds):
        model = XGBClassifier()
        model.load_model(f'model_output/model_{i}.json')
        models.append(model)

    X, y, ids = fetch_data(nullonly=True)

    output = pd.DataFrame({'event_id': ids})

    if len(X):
        for i, model in enumerate(models):
            output[f'model_{i}'] = model.predict_proba(X)[:, 1]

    output['consensus'] = output.drop('event_id', axis=1).mean(axis=1)
    output = output[['event_id', 'consensus']]

    engine = create_engine(conn_string)
    output.to_sql('temp', engine, if_exists='replace', index=False)
    with engine.begin() as conn:
        query = """
            UPDATE events
            SET xg = temp.consensus
            FROM temp
            WHERE events.event_id = temp.event_id;
            DROP TABLE temp
        """
        conn.execute(text(query))

if __name__ == "__main__":
    calc_new_xg()