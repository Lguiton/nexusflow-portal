import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import io

class ChurnPredictionAgent:
    def __init__(self):
        # Initialize a Random Forest model
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self._bootstrap_model()

    def _bootstrap_model(self):
        """Generates synthetic historical data to train the model immediately on boot."""
        np.random.seed(42)
        n_samples = 500
        
        # Simulated Historical Features
        mrr = np.random.normal(5000, 1500, n_samples)
        days_since_login = np.random.normal(15, 10, n_samples)
        support_tickets = np.random.poisson(2, n_samples)
        
        # Logic: High inactivity + high friction (tickets) = churn
        churn = ((days_since_login > 20) & (support_tickets > 3)).astype(int)
        
        df = pd.DataFrame({
            'mrr': mrr,
            'days_since_login': days_since_login,
            'support_tickets': support_tickets,
            'churn': churn
        })
        
        X = df[['mrr', 'days_since_login', 'support_tickets']]
        y = df['churn']
        
        # Train the model
        self.model.fit(X, y)
        print("nexus_sys: Churn Prediction Sub-Agent trained and online.")

    def analyze_csv(self, file_contents: bytes) -> dict:
        """Ingests a CSV, runs inference, and returns at-risk client insights."""
        try:
            # Load CSV bytes into a pandas DataFrame
            df = pd.read_csv(io.BytesIO(file_contents))
            
            required_cols = ['client_id', 'mrr', 'days_since_login', 'support_tickets']
            if not all(col in df.columns for col in required_cols):
                return {"error": f"CSV missing required telemetry columns: {required_cols}"}

            # Extract features and predict
            X_new = df[['mrr', 'days_since_login', 'support_tickets']]
            predictions = self.model.predict(X_new)
            probabilities = self.model.predict_proba(X_new)[:, 1] # Class 1 (Churn) probability

            df['churn_risk_percent'] = (probabilities * 100).round(1)
            df['prediction'] = predictions

            # Isolate the high-risk accounts
            at_risk_df = df[df['prediction'] == 1].sort_values(by='churn_risk_percent', ascending=False)
            at_risk_records = at_risk_df.to_dict(orient='records')

            return {
                "status": "success",
                "total_analyzed": len(df),
                "at_risk_count": len(at_risk_records),
                "high_risk_clients": at_risk_records,
                "insight": f"Agent detected {len(at_risk_records)} accounts at severe risk of churn based on behavioral telemetry."
            }
        except Exception as e:
            return {"error": f"Data Science Execution Failure: {str(e)}"}

# Instantiate the agent so it's ready in memory when FastAPI boots
churn_agent = ChurnPredictionAgent()