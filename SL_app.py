# app.py - Brown League Dashboard
import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="Brown League Dashboard", 
    page_icon="🤎", 
    layout="wide"
)

class GoogleSheetsManager:
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
        try:
            worksheet = self.spreadsheet.worksheet(sheet_name)
            data = worksheet.get_all_records()
            return pd.DataFrame(data)
        except:
            return pd.DataFrame()
    
    def update_worksheet(self, sheet_name, df):
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
    def __init__(self):
        self.base_url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
        self.league_id = "1732780114"
        self.season = 2025
        
        self.cookies = {
            "SWID": st.secrets.get('swid', ''),
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
        
        # Brown League team to manager mapping
        manager_mapping = {
            1: 'John Van Handel',
            2: 'Andrew Lupario', 
            3: 'Matt Plantz',
            4: 'Josh Brechtel',
            5: 'Michael McCormick',
            6: 'Will Grant'
        }
        
        teams = []
        for team in data.get('teams', []):
            team_id = team['id']
            manager_name = manager_mapping.get(team_id, f"Team {team_id}")
            
            teams.append({
                'team_id': team_id,
                'team_name': manager_name,  # Use manager name as display name
                'location': team.get('location', 'Team'),
                'nickname': team.get('nickname', str(team_id)),
                'owner': team.get('primaryOwner', 'Unknown'),
                'league': 'brown_line'
            })
        
        return pd.DataFrame(teams)
    
    def get_live_scores(self, week):
        """Get live scores by calculating from player stats"""
        try:
            data = self.make_request("mRoster", week)
            
            team_scores = {}
            
            # Debug: Let's see what lineup slots we're getting
            if st.sidebar.checkbox("Debug Mode - Show Lineup Slots"):
                st.subheader("Debug: Lineup Slot Analysis")
                for team in data.get('teams', []):
                    team_name = f"{team.get('location', 'Team')} {team.get('nickname', str(team['id']))}"
                    st.write(f"**{team_name} (ID: {team['id']})**")
                    
                    roster = team.get('roster', {}).get('entries', [])
                    slot_analysis = {}
                    
                    for player_entry in roster:
                        lineup_slot = player_entry.get('lineupSlotId', -1)
                        player_pool_entry = player_entry.get('playerPoolEntry', {})
                        applied_total = player_pool_entry.get('appliedStatTotal', 0)
                        player_name = player_pool_entry.get('player', {}).get('fullName', 'Unknown')
                        
                        if lineup_slot not in slot_analysis:
                            slot_analysis[lineup_slot] = []
                        slot_analysis[lineup_slot].append({
                            'player': player_name,
                            'points': applied_total
                        })
                    
                    # Show slot breakdown
                    for slot_id, players in sorted(slot_analysis.items()):
                        st.write(f"  Slot {slot_id}: {len(players)} players")
                        for player in players:
                            st.write(f"    - {player['player']}: {player['points']} pts")
                    st.write("---")
            
            # Calculate scores - using the correct starting lineup slots
            # Starting positions: QB(0), TE(6), DL(11), DB(14), P(18), HC(19), FLEX(23)
            # Excluding Slot 20 which is bench
            starting_positions = [0, 6, 11, 14, 18, 19, 23]
            
            for team in data.get('teams', []):
                team_id = team['id']
                total_score = 0
                
                roster = team.get('roster', {}).get('entries', [])
                for player_entry in roster:
                    lineup_slot = player_entry.get('lineupSlotId', -1)
                    
                    # Only starting lineup positions
                    if lineup_slot in starting_positions:
                        player_pool_entry = player_entry.get('playerPoolEntry', {})
                        applied_total = player_pool_entry.get('appliedStatTotal', 0)
                        total_score += applied_total
                
                team_scores[team_id] = total_score
            
            return team_scores
            
        except Exception as e:
            st.error(f"Error getting live scores: {e}")
            return {}
    
    def get_matchups(self, week=None):
        """Get matchup structure"""
        data = self.make_request("mMatchup", week)
        
        matchups = []
        for game in data.get('schedule', []):
            if 'away' not in game or 'home' not in game:
                continue
                
            week_num = game.get('matchupPeriodId', 0)
            away_team = game['away'].get('teamId')
            home_team = game['home'].get('teamId')
            
            if not away_team or not home_team:
                continue
            
            matchups.append({
                'week': week_num,
                'away_team_id': away_team,
                'home_team_id': home_team
            })
        
        return pd.DataFrame(matchups)
    
    def is_week_complete(self, week):
        """Check if a week is complete (Tuesday morning after the week)"""
        current_date = datetime.now()
        
        # NFL 2025 season started September 4, 2025
        week_1_start = datetime(2025, 9, 4)  # Thursday Sept 4, 2025
        week_start = week_1_start + timedelta(weeks=week-1)
        week_complete = week_start + timedelta(days=5)  # Tuesday after the week
        
        return current_date >= week_complete
    
    def get_current_week(self):
        """Calculate current NFL week"""
        season_start = datetime(2025, 9, 4)  # Sept 4, 2025
        current_date = datetime.now()
        days_since_start = (current_date - season_start).days
        current_week = min(max(1, (days_since_start // 7) + 1), 14)
        return current_week

def main():
    st.title("🤎 Brown League Dashboard")
    st.sidebar.title("Controls")
    
    # Initialize API
    espn_api = ESPNFantasyAPI()
    sheets_manager = GoogleSheetsManager()
    
    # Get current week
    current_week = espn_api.get_current_week()
    
    # Week selector
    selected_week = st.sidebar.selectbox(
        "Select Week",
        range(1, 15),
        index=current_week-1
    )
    
    # Manual refresh button
    if st.sidebar.button("🔄 Refresh Data", type="primary"):
        refresh_data(sheets_manager, espn_api, selected_week)
    
    # Page selector
    page = st.sidebar.selectbox(
        "Select View", 
        ["Live Scores", "Weekly Rankings", "Season Standings"]
    )
    
    # Load teams data
    teams_df = sheets_manager.get_worksheet_data("teams")
    if teams_df.empty:
        with st.spinner("Loading teams from ESPN..."):
            teams_df = espn_api.get_teams()
            if not teams_df.empty:
                sheets_manager.update_worksheet("teams", teams_df)
    
    if teams_df.empty:
        st.error("Unable to load team data")
        return
    
    # Render selected page
    if page == "Live Scores":
        show_live_scores(teams_df, espn_api, sheets_manager, selected_week)
    elif page == "Weekly Rankings":
        show_weekly_rankings(teams_df, espn_api, selected_week)
    elif page == "Season Standings":
        show_season_standings(teams_df, sheets_manager)

def refresh_data(sheets_manager, espn_api, week):
    """Refresh data from ESPN"""
    with st.spinner("Refreshing data..."):
        try:
            # Get teams
            teams_df = espn_api.get_teams()
            sheets_manager.update_worksheet("teams", teams_df)
            
            # Get current scores and matchups
            matchups_df = espn_api.get_matchups(week)
            live_scores = espn_api.get_live_scores(week)
            
            if not matchups_df.empty and live_scores:
                weekly_data = process_weekly_data(teams_df, matchups_df, live_scores, espn_api, week)
                
                # Only save to sheets if week is complete
                if espn_api.is_week_complete(week):
                    sheets_manager.update_worksheet("weekly_scores", weekly_data)
                    st.success("Week complete - Data saved to Google Sheets!")
                else:
                    st.success("Live data refreshed!")
            else:
                st.warning("No matchup data available for this week")
                
        except Exception as e:
            st.error(f"Error refreshing data: {e}")

def process_weekly_data(teams_df, matchups_df, live_scores, espn_api, week):
    """Process weekly scoring data"""
    week_complete = espn_api.is_week_complete(week)
    weekly_data = []
    
    week_matchups = matchups_df[matchups_df['week'] == week]
    
    for _, matchup in week_matchups.iterrows():
        away_team = matchup['away_team_id']
        home_team = matchup['home_team_id']
        away_score = live_scores.get(away_team, 0)
        home_score = live_scores.get(home_team, 0)
        
        # Calculate intra-league points only if week is complete
        if week_complete:
            if away_score > home_score:
                away_intra_points = 1
                home_intra_points = 0
            elif home_score > away_score:
                away_intra_points = 0
                home_intra_points = 1
            else:
                away_intra_points = 0.5
                home_intra_points = 0.5
        else:
            away_intra_points = 0
            home_intra_points = 0
        
        # Away team data
        weekly_data.append({
            'week': week,
            'team_id': away_team,
            'actual_score': away_score,
            'opponent_id': home_team,
            'opponent_score': home_score,
            'intra_league_points': away_intra_points,
            'cross_league_points': 0,
            'top6_points': 1 if week_complete else 0,  # All teams get top6 since only 6 teams
            'total_weekly_points': away_intra_points + (1 if week_complete else 0),
            'week_complete': week_complete
        })
        
        # Home team data
        weekly_data.append({
            'week': week,
            'team_id': home_team,
            'actual_score': home_score,
            'opponent_id': away_team,
            'opponent_score': away_score,
            'intra_league_points': home_intra_points,
            'cross_league_points': 0,
            'top6_points': 1 if week_complete else 0,
            'total_weekly_points': home_intra_points + (1 if week_complete else 0),
            'week_complete': week_complete
        })
    
    return pd.DataFrame(weekly_data)

def show_live_scores(teams_df, espn_api, sheets_manager, week):
    """Show live scores for selected week"""
    st.header(f"Week {week} Live Scores")
    
    # Get current data
    matchups_df = espn_api.get_matchups(week)
    live_scores = espn_api.get_live_scores(week)
    
    if matchups_df.empty or not live_scores:
        st.warning(f"No data available for Week {week}")
        return
    
    # Check if week is complete
    week_complete = espn_api.is_week_complete(week)
    
    if week_complete:
        st.success("✅ Week Complete - Points Awarded")
    else:
        st.info("🔄 Live Scoring - Points will be awarded Tuesday morning")
    
    # Show matchups
    st.subheader("Current Matchups")
    
    week_matchups = matchups_df[matchups_df['week'] == week]
    
    for _, matchup in week_matchups.iterrows():
        away_team = matchup['away_team_id']
        home_team = matchup['home_team_id']
        away_score = live_scores.get(away_team, 0)
        home_score = live_scores.get(home_team, 0)
        
        away_name = teams_df[teams_df['team_id'] == away_team]['team_name'].iloc[0]
        home_name = teams_df[teams_df['team_id'] == home_team]['team_name'].iloc[0]
        
        col1, col2, col3 = st.columns([2, 1, 2])
        
        with col1:
            if away_score > home_score:
                st.write(f"**{away_name}** 🔥")
            else:
                st.write(f"{away_name}")
            st.metric("Score", f"{away_score:.1f}")
        
        with col2:
            st.write("**VS**")
            if week_complete:
                if away_score > home_score:
                    st.write("← Winner")
                elif home_score > away_score:
                    st.write("Winner →")
                else:
                    st.write("Tie")
        
        with col3:
            if home_score > away_score:
                st.write(f"**{home_name}** 🔥")
            else:
                st.write(f"{home_name}")
            st.metric("Score", f"{home_score:.1f}")
        
        st.divider()

def show_weekly_rankings(teams_df, espn_api, week):
    """Show weekly rankings"""
    st.header(f"Week {week} Rankings")
    
    live_scores = espn_api.get_live_scores(week)
    
    if not live_scores:
        st.warning(f"No data available for Week {week}")
        return
    
    # Create rankings
    rankings = []
    for team_id, score in live_scores.items():
        team_name = teams_df[teams_df['team_id'] == team_id]['team_name'].iloc[0]
        rankings.append({'team_id': team_id, 'team_name': team_name, 'score': score})
    
    rankings_df = pd.DataFrame(rankings)
    rankings_df = rankings_df.sort_values('score', ascending=False).reset_index(drop=True)
    rankings_df['rank'] = rankings_df.index + 1
    
    # Display rankings
    for _, row in rankings_df.iterrows():
        col1, col2, col3 = st.columns([1, 4, 2])
        
        with col1:
            st.write(f"**#{row['rank']}**")
        with col2:
            st.write(f"**{row['team_name']}**")
        with col3:
            st.metric("Score", f"{row['score']:.1f}")

def show_season_standings(teams_df, sheets_manager):
    """Show season standings"""
    st.header("Season Standings")
    
    weekly_scores_df = sheets_manager.get_worksheet_data("weekly_scores")
    
    if weekly_scores_df.empty:
        st.warning("No historical data available yet")
        return
    
    # Calculate season totals
    standings = weekly_scores_df.groupby('team_id').agg({
        'intra_league_points': 'sum',
        'cross_league_points': 'sum',
        'top6_points': 'sum',
        'total_weekly_points': 'sum',
        'actual_score': 'sum'
    }).reset_index()
    
    # Merge with team names
    standings = standings.merge(teams_df[['team_id', 'team_name']], on='team_id')
    standings = standings.sort_values('total_weekly_points', ascending=False).reset_index(drop=True)
    standings['rank'] = standings.index + 1
    
    st.dataframe(
        standings[['rank', 'team_name', 'total_weekly_points', 'intra_league_points', 'top6_points', 'actual_score']],
        column_config={
            "rank": "Rank",
            "team_name": "Team",
            "total_weekly_points": "Total Points",
            "intra_league_points": "League Wins",
            "top6_points": "Top 6 Wins",
            "actual_score": "Total Fantasy Points"
        },
        use_container_width=True,
        hide_index=True
    )

if __name__ == "__main__":
    main()
