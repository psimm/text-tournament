import numpy as np
import polars as pl
from scipy.optimize import minimize


def bradley_terry(df: pl.DataFrame) -> pl.DataFrame:
    # Get unique competitors and create a mapping to indices
    competitors = sorted(set(df["winner"].unique()) | set(df["loser"].unique()))
    n = len(competitors)
    company_to_index = {company: i for i, company in enumerate(competitors)}

    # Create a matrix to store win counts
    wins = np.zeros((n, n))
    win_counts = df.group_by("winner", "loser").agg(pl.len())
    for row in win_counts.to_dicts():
        i, j = company_to_index[row["winner"]], company_to_index[row["loser"]]
        wins[i, j] = row["len"]

    # Define the negative log-likelihood function
    def neg_log_likelihood(params):
        strengths = np.exp(params)
        total = 0
        for i in range(n):
            for j in range(n):
                if i != j:
                    pij = strengths[i] / (strengths[i] + strengths[j])
                    total += wins[i, j] * np.log(pij) + wins[j, i] * np.log(1 - pij)
        return -total

    # Optimize to find the best parameters
    initial_params = np.zeros(n)
    result = minimize(neg_log_likelihood, initial_params, method="BFGS")
    strengths = np.exp(result.x)

    return pl.DataFrame({"competitor": competitors, "strength": strengths})
