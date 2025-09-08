# app.py - Brown League Fantasy Dashboard
import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# Configure page
st.set_page_config(
    page_title="Brown League Fantasy Dashboard",
    page_icon="🤎",
    layout="wide"
)

class GoogleSheetsManager:
    """Handles all Google Sheets operations"""
    
    def __init__(self):
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds_dict = {
            "type": st.secrets["google"]["type"],
            "project_id": st.secrets["google"]["project_id"],
            "private_key_id": st.secrets["google"]["private_key_id"],
            "private_key": st.secrets["google"]["private_key"],
            "client_email": st.secrets["google"]["client_email"],
            "client_id": st.secrets["google"]["client_id"],
            "auth_uri": st.secrets["google"]["auth_uri"],
            "token_uri": st.secrets["google"]["token_uri"],
        }
        
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
        self.gc = gspread.authorize(credentials)
        self.spreadsheet = self.gc.open_by_key(st.secrets["google"]["sheet_id"])
    
    def get_worksheet_data(self, sheet_name):
        """Get data from a worksheet, return empty DataFrame if sheet doesn't exist"""
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
            data = worksheet.get_all_records()
            return pd.DataFrame(data)
        except:
            return pd.DataFrame()
    
    def update_worksheet(self, sheet_name, df):
        """Update a worksheet with new data"""
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
            worksheet.clear()
            if not df.empty:
                worksheet.update([df.columns.values.tolist()] + df.values.tolist())
            return True
        except Exception as e:
            st.error(f"Error updating {sheet_name}: {e}")
            return False

class ESPNFantasyAPI:
    """Handles ESPN Fantasy Football API calls"""
    
    def __init__(self):
        self.base_url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
        self.league_id = "1732780114"  # Brown League
        self.season = 2024
        
        # Authentication cookies
        self.cookies = {
            "swid": st.secrets.get('swid', ''),
            "espn_s2": st.secrets.get('espn_s2', '')
        }
    
    def make_request(self, view, week=None):
        """Make API request to ESPN"""
        url = f"{self.base_url}/{self.season}/segments/0/leagues/{self.league_id}"
        params = {"view": view}
        
        if week:
            params["scoringPeriodId"] = week
        
        response = requests.get(url, params=params, cookies=self.cookies)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"ESPN API Error: {response.status_code}")
    
    def get_teams(self):
        """Get team information"""
        data = self.make_request("mTeam")
        
        teams = []
        for team in data.get('teams', []):
            teams.append({
                'team_id': team['id'],
                'team_name': f"{team['location']} {team['nickname']}",
                'owner': team.get('primaryOwner', ''),
                'league': 'brown_line'
            })
        
        return pd.DataFrame(teams)
    
    def get_matchups(self, week=None):
        """Get matchup data for a specific week or all weeks"""
        data = self.make_request("mMatchup", week)
        
        matchups = []
        for game in data.get('schedule', []):
            if 'away' in game and 'home' in game:
                matchups.append({
                    'week': game['matchupPeriodId'],
                    'away_team_id': game['away']['teamId'],
                    'away_score': game['away'].get('totalPoints', 0),
                    'home_team_id': game['home']['teamId'],
                    'home_score': game['home'].get('totalPoints', 0)
                })
        
        return pd.DataFrame(matchups)
    
    def get_current_week(self):
        """Calculate current NFL week"""
        # NFL 2024 season started September 5
        season_start = datetime(2024, 9, 5)
        current_date = datetime.now()
        days_since_start = (current_date - season_start).days
        current_week = min(max(1, (days_since_start // 7) + 1), 14)
        return current_week

class ScoreCalculator:
    """Calculates fantasy scoring based on league rules"""
    
    def __init__(self, teams_df, matchups_df):
        self.teams_df = teams_df
        self.matchups_df = matchups_df
    
    def calculate_weekly_scores(self, week):
        """Calculate scores for a specific week"""
        week_matchups = self.matchups_df[self.matchups_df['week'] == week].copy()
        
        if week_matchups.empty:
            return pd.DataFrame()
        
        # Create a list to store team weekly data
        weekly_data = []
        
        for _, matchup in week_matchups.iterrows():
            away_team = matchup['away_team_id']
            home_team = matchup['home_team_id'] 
            away_score = matchup['away_score']
            home_score = matchup['home_score']
            
            # Determine winner (1 point for intra-league win)
            if away_score > home_score:
                away_intra_points = 1
                home_intra_points = 0
            elif home_score > away_score:
                away_intra_points = 0
                home_intra_points = 1
            else:  # Tie
                away_intra_points = 0.5
                home_intra_points = 0.5
            
            # Add away team data
            weekly_data.append({
                'week': week,
                'team_id': away_team,
                'actual_score': away_score,
                'opponent_id': home_team,
                'opponent_score': home_score,
                'intra_league_points': away_intra_points
            })
            
            # Add home team data  
            weekly_data.append({
                'week': week,
                'team_id': home_team,
                'actual_score': home_score,
                'opponent_id': away_team,
                'opponent_score': away_score,
                'intra_league_points': home_intra_points
            })
        
        weekly_df = pd.DataFrame(weekly_data)
        
        # Calculate top 6 points (all teams get 1 point since there are only 6 teams)
        # In a 6-team league, everyone gets top 6 points!
        weekly_df['top6_points'] = 1
        
        # For now, no cross-league points since we're testing one league
        weekly_df['cross_league_points'] = 0
        
        # Calculate total weekly points
        weekly_df['total_weekly_points'] = (
            weekly_df['intra_league_points'] + 
            weekly_df['cross_league_points'] + 
            weekly_df['top6_points']
        )
        
        return weekly_df
    
    def calculate_season_standings(self, all_weekly_data):
        """Calculate season-long standings"""
        if all_weekly_data.empty:
            return pd.DataFrame()
        
        standings = all_weekly_data.groupby('team_id').agg({
            'intra_league_points': 'sum',
            'cross_league_points': 'sum',
            'top6_points': 'sum', 
            'total_weekly_points': 'sum',
            'actual_score': 'sum'
        }).reset_index()
        
        standings.rename(columns={
            'intra_league_points': 'intra_league_wins',
            'cross_league_points': 'cross_league_wins',
            'top6_points': 'top6_wins',
            'total_weekly_points': 'total_wins',
            'actual_score': 'total_points_scored'
        }, inplace=True)
        
        # Sort by total wins, then by points scored
        standings = standings.sort_values(['total_wins', 'total_points_scored'], ascending=[False, False])
        
        return standings

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_data():
    """Load and process all data"""
    sheets_manager = GoogleSheetsManager()
    espn_api = ESPNFantasyAPI()
    
    return sheets_manager, espn_api

def main():
    st.title("🤎 Brown League Fantasy Dashboard")
    st.sidebar.title("Controls")
    
    # Load managers
    sheets_manager, espn_api = load_data()
    
    # Get current week
    current_week = espn_api.get_current_week()
    
    # Week selector
    selected_week = st.sidebar.selectbox(
        "Select Week",
        range(1, 15),  # Weeks 1-14
        index=current_week-1
    )
    
    # Refresh button
    if st.sidebar.button("🔄 Refresh Data", type="primary"):
        st.cache_data.clear()
        refresh_data(sheets_manager, espn_api, selected_week)
        st.rerun()
    
    # Page selector
    page = st.sidebar.selectbox(
        "Select View", 
        ["Team Overview", "Weekly Scores", "Season Standings", "Raw Data"]
    )
    
    # Load current data
    teams_df = sheets_manager.get_worksheet_data("teams")
    weekly_scores_df = sheets_manager.get_worksheet_data("weekly_scores")
    
    if page == "Team Overview":
        show_team_overview(teams_df, weekly_scores_df, current_week)
    elif page == "Weekly Scores":
        show_weekly_scores(teams_df, weekly_scores_df, selected_week)
    elif page == "Season Standings":
        show_season_standings(teams_df, weekly_scores_df)
    elif page == "Raw Data":
        show_raw_data(sheets_manager)

def refresh_data(sheets_manager, espn_api, week):
    """Refresh data from ESPN API"""
    try:
        with st.spinner("Fetching data from ESPN..."):
            # Get teams data
            teams_df = espn_api.get_teams()
            
            # Get matchups data
            matchups_df = espn_api.get_matchups()
            
            # Calculate scores
            calculator = ScoreCalculator(teams_df, matchups_df)
            
            # Process all available weeks
            all_weekly_data = []
            available_weeks = sorted(matchups_df['week'].unique())
            
            for w in available_weeks:
                week_data = calculator.calculate_weekly_scores(w)
                if not week_data.empty:
                    all_weekly_data.append(week_data)
            
            if all_weekly_data:
                combined_weekly_df = pd.concat(all_weekly_data, ignore_index=True)
                
                # Update Google Sheets
                sheets_manager.update_worksheet("teams", teams_df)
                sheets_manager.update_worksheet("weekly_scores", combined_weekly_df)
                
                # Calculate and update standings
                standings_df = calculator.calculate_season_standings(combined_weekly_df)
                sheets_manager.update_worksheet("season_standings", standings_df)
                
                st.success("Data updated successfully!")
            else:
                st.warning("No matchup data available yet")
                
    except Exception as e:
        st.error(f"Error refreshing data: {str(e)}")

def show_team_overview(teams_df, weekly_scores_df, current_week):
    """Show team overview page"""
    st.header("Team Overview")
    
    if teams_df.empty:
        st.warning("No team data available. Click 'Refresh Data' to load from ESPN.")
        return
    
    # Show teams
    st.subheader("Brown League Teams")
    st.dataframe(teams_df[['team_name', 'owner']], use_container_width=True)
    
    # Show current week info
    if not weekly_scores_df.empty:
        current_week_data = weekly_scores_df[weekly_scores_df['week'] == current_week]
        if not current_week_data.empty:
            st.subheader(f"Week {current_week} Scores")
            
            # Merge with team names
            display_data = current_week_data.merge(
                teams_df[['team_id', 'team_name']], on='team_id', how='left'
            ).sort_values('actual_score', ascending=False)
            
            for idx, row in display_data.iterrows():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.write(f"**{row['team_name']}**")
                with col2:
                    st.metric("Score", f"{row['actual_score']:.1f}")
                with col3:
                    st.metric("Points", int(row['total_weekly_points']))

def show_weekly_scores(teams_df, weekly_scores_df, selected_week):
    """Show weekly scores page"""
    st.header(f"Week {selected_week} Detailed Results")
    
    if weekly_scores_df.empty or teams_df.empty:
        st.warning("No data available. Click 'Refresh Data' to load from ESPN.")
        return
    
    week_data = weekly_scores_df[weekly_scores_df['week'] == selected_week]
    if week_data.empty:
        st.warning(f"No data available for Week {selected_week}")
        return
    
    # Merge with team names
    display_data = week_data.merge(
        teams_df[['team_id', 'team_name']], on='team_id', how='left'
    )
    display_data = display_data.merge(
        teams_df[['team_id', 'team_name']], 
        left_on='opponent_id', right_on='team_id', 
        how='left', suffixes=('', '_opp')
    )
    
    # Sort by actual score
    display_data = display_data.sort_values('actual_score', ascending=False)
    
    st.subheader("Matchup Results")
    
    for idx, row in display_data.iterrows():
        col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
        
        with col1:
            win_indicator = "🏆" if row['intra_league_points'] == 1 else "❌" if row['intra_league_points'] == 0 else "🤝"
            st.write(f"{win_indicator} **{row['team_name']}** vs {row['team_name_opp']}")
        
        with col2:
            st.write(f"{row['actual_score']:.1f} - {row['opponent_score']:.1f}")
        
        with col3:
            st.metric("League", int(row['intra_league_points']))
        
        with col4:
            st.metric("Total", int(row['total_weekly_points']))

def show_season_standings(teams_df, weekly_scores_df):
    """Show season standings page"""
    st.header("Season Standings")
    
    if weekly_scores_df.empty or teams_df.empty:
        st.warning("No data available. Click 'Refresh Data' to load from ESPN.")
        return
    
    # Calculate standings
    standings = weekly_scores_df.groupby('team_id').agg({
        'intra_league_points': 'sum',
        'cross_league_points': 'sum',
        'top6_points': 'sum',
        'total_weekly_points': 'sum',
        'actual_score': 'sum'
    }).reset_index()
    
    # Merge with team names
    standings = standings.merge(teams_df[['team_id', 'team_name']], on='team_id')
    
    # Sort by total wins
    standings = standings.sort_values(['total_weekly_points', 'actual_score'], ascending=[False, False])
    standings = standings.reset_index(drop=True)
    standings['rank'] = standings.index + 1
    
    # Display standings table
    display_columns = ['rank', 'team_name', 'total_weekly_points', 'intra_league_points', 
                      'top6_points', 'actual_score']
    
    st.dataframe(
        standings[display_columns],
        column_config={
            "rank": "Rank",
            "team_name": "Team",
            "total_weekly_points": "Total Wins",
            "intra_league_points": "League Wins",
            "top6_points": "Top 6 Wins",
            "actual_score": "Total Points"
        },
        use_container_width=True,
        hide_index=True
    )

def show_raw_data(sheets_manager):
    """Show raw data for debugging"""
    st.header("Raw Data (Debug)")
    
    tabs = st.tabs(["Teams", "Weekly Scores", "Season Standings"])
    
    with tabs[0]:
        st.subheader("Teams Data")
        teams_df = sheets_manager.get_worksheet_data("teams")
        if not teams_df.empty:
            st.dataframe(teams_df)
        else:
            st.write("No teams data available")
    
    with tabs[1]:
        st.subheader("Weekly Scores Data")
        weekly_df = sheets_manager.get_worksheet_data("weekly_scores")
        if not weekly_df.empty:
            st.dataframe(weekly_df)
        else:
            st.write("No weekly scores data available")
    
    with tabs[2]:
        st.subheader("Season Standings Data")
        standings_df = sheets_manager.get_worksheet_data("season_standings")
        if not standings_df.empty:
            st.dataframe(standings_df)
        else:
            st.write("No standings data available")

if __name__ == "__main__":
    main()


# requirements.txt
streamlit
pandas
numpy
requests
gspread
google-auth
google-auth-oauthlib
google-auth-httplib2


# config.py - Configuration settings
"""Configuration settings for the Brown League Fantasy Dashboard"""

# League Information
LEAGUE_ID = "1732780114"
SEASON = 2024
MAX_WEEKS = 14

# ESPN API Settings  
ESPN_BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"

# Google Sheets Configuration
SHEET_NAMES = {
    'teams': 'teams',
    'weekly_scores': 'weekly_scores', 
    'season_standings': 'season_standings',
    'matchups': 'matchups'
}

# Scoring Rules
SCORING_RULES = {
    'intra_league_win': 1,      # 1 point for beating opponent in your league
    'cross_league_win': 1,      # 1 point for beating cross-league opponent  
    'top6_placement': 1,        # 1 point for being in top 6 scorers
}

# Manager Information (ESPN team_id to manager name mapping)
# You may need to update these based on actual ESPN team IDs
MANAGERS = {
    1: 'Matt',
    2: 'Michael', 
    3: 'Andrew',
    4: 'John',
    5: 'Josh',
    6: 'Will'
}
