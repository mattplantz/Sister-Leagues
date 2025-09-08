# app.py - Sister Leagues Dashboard
import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(
    page_title="Sister Leagues Dashboard", 
    page_icon="🏈", 
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
    def __init__(self, league_type="brown"):
        self.base_url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons"
        self.season = 2025
        self.league_type = league_type
        
        if league_type == "brown":
            self.league_id = "1732780114"
            self.cookies = {
                "SWID": st.secrets.get('swid', ''),
                "espn_s2": st.secrets.get('espn_s2', '')
            }
        else:  # red league
            self.league_id = "1019746952"
            self.cookies = {
                "SWID": st.secrets.get('red_swid', ''),
                "espn_s2": st.secrets.get('red_espn_s2', '')
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
            raise Exception(f"ESPN API Error for {self.league_type}: {response.status_code}")
    
    def get_teams(self):
        """Get team information"""
        data = self.make_request("mTeam")
        
        # Manager mappings
        if self.league_type == "brown":
            manager_mapping = {
                1: 'John Van Handel',
                2: 'Andrew Lupario', 
                3: 'Matt Plantz',
                4: 'Josh Brechtel',
                5: 'Michael McCormick',
                6: 'Will Grant'
            }
        else:  # red league - These are placeholders, update based on debug info
            manager_mapping = {
                1: 'Red Team 1 Manager',  # Update with actual manager name
                2: 'Red Team 2 Manager',  # Update with actual manager name
                3: 'Red Team 3 Manager',  # Update with actual manager name
                4: 'Red Team 4 Manager',  # Update with actual manager name
                5: 'Red Team 5 Manager',  # Update with actual manager name
                6: 'Red Team 6 Manager'   # Update with actual manager name
            }
        
        teams = []
        for team in data.get('teams', []):
            team_id = team['id']
            
            # Use manager names for both leagues now
            team_name = manager_mapping.get(team_id, f"Team {team_id}")
            
            # Make Red League team IDs unique by adding 100
            if self.league_type == "red":
                team_id = team_id + 100
            
            teams.append({
                'team_id': team_id,
                'team_name': team_name,
                'location': team.get('location', 'Team'),
                'nickname': team.get('nickname', str(team_id)),
                'owner': team.get('primaryOwner', 'Unknown'),
                'league': self.league_type
            })
        
        return pd.DataFrame(teams)
    
    def get_live_scores(self, week):
        """Get live scores by calculating from player stats"""
        try:
            data = self.make_request("mRoster", week)
            
            team_scores = {}
            
            # Starting positions: QB(0), TE(6), DL(11), DB(14), P(18), HC(19), FLEX(23)
            starting_positions = [0, 6, 11, 14, 18, 19, 23]
            
            for team in data.get('teams', []):
                espn_team_id = team['id']  # Raw ESPN ID (1, 2, 3, etc.)
                total_score = 0
                
                roster = team.get('roster', {}).get('entries', [])
                for player_entry in roster:
                    lineup_slot = player_entry.get('lineupSlotId', -1)
                    
                    if lineup_slot in starting_positions:
                        player_pool_entry = player_entry.get('playerPoolEntry', {})
                        applied_total = player_pool_entry.get('appliedStatTotal', 0)
                        total_score += applied_total
                
                # Store with raw ID first
                team_scores[espn_team_id] = total_score
            
            # Convert all keys to prefixed strings
            final_scores = {}
            for raw_id, score in team_scores.items():
                prefixed_key = f"{self.league_type}_{raw_id}"
                final_scores[prefixed_key] = score
            
            return final_scores
        
        except Exception as e:
            st.error(f"Error getting live scores for {self.league_type}: {e}")
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
                'home_team_id': home_team,
                'league': self.league_type
            })
        
        return pd.DataFrame(matchups)
    
    def is_week_complete(self, week):
        """Check if a week is complete (Tuesday morning after the week)"""
        current_date = datetime.now()
        week_1_start = datetime(2025, 9, 4)
        week_start = week_1_start + timedelta(weeks=week-1)
        week_complete = week_start + timedelta(days=5)
        return current_date >= week_complete
    
    def get_current_week(self):
        """Calculate current NFL week"""
        season_start = datetime(2025, 9, 4)
        current_date = datetime.now()
        days_since_start = (current_date - season_start).days
        current_week = min(max(1, (days_since_start // 7) + 1), 14)
        return current_week

class ScoreCalculator:
    def __init__(self, all_teams_df, brown_api, red_api, sheets_manager):
        self.all_teams_df = all_teams_df
        self.brown_api = brown_api
        self.red_api = red_api
        self.sheets_manager = sheets_manager
    
    def calculate_weekly_scores(self, week):
        """Calculate comprehensive weekly scores for both leagues"""
        # Get scores from both leagues (these should return prefixed IDs)
        brown_scores = self.brown_api.get_live_scores(week)
        red_scores = self.red_api.get_live_scores(week)
        
        # Get intra-league matchups (these should return prefixed IDs)
        brown_matchups = self.brown_api.get_matchups(week)
        red_matchups = self.red_api.get_matchups(week)
        
        # Get cross-league matchups from Google Sheets
        cross_matchups = self.sheets_manager.get_worksheet_data("matchups")
        week_cross_matchups = cross_matchups[cross_matchups['week'] == week] if not cross_matchups.empty else pd.DataFrame()
        
        # Check if week is complete
        week_complete = self.brown_api.is_week_complete(week)
        
        # Combine all scores (both should use prefixed IDs now)
        all_scores = {**brown_scores, **red_scores}
        
        # Calculate top 6 teams across both leagues (using prefixed IDs)
        top6_teams = []
        if week_complete:
            sorted_scores = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
            top6_teams = [prefixed_team_id for prefixed_team_id, score in sorted_scores[:6]]
        
        # Process each league
        weekly_data = []
        
        # Process Brown League
        brown_data = self._process_league_scores(
            brown_scores, brown_matchups, week_cross_matchups, 
            'brown', week, week_complete, top6_teams
        )
        weekly_data.extend(brown_data)
        
        # Process Red League  
        red_data = self._process_league_scores(
            red_scores, red_matchups, week_cross_matchups, 
            'red', week, week_complete, top6_teams
        )
        weekly_data.extend(red_data)
        
        result_df = pd.DataFrame(weekly_data)
        
        return result_df
    
    def _process_league_scores(self, scores, matchups, cross_matchups, league, week, week_complete, top6_teams):
        """Process scores for a single league"""
        league_data = []
        week_matchups = matchups[matchups['week'] == week] if not matchups.empty else pd.DataFrame()
        
        # Get cross-league opponent mapping
        cross_opponents = {}
        if not cross_matchups.empty:
            for _, match in cross_matchups.iterrows():
                brown_manager = match.get('brown_league_team', '')
                red_manager = match.get('red_league_team', '')
                
                # Find Brown League team by manager name
                brown_team = self.all_teams_df[
                    (self.all_teams_df['team_name'] == brown_manager) & 
                    (self.all_teams_df['league'] == 'brown')
                ]
                
                # Find Red League team by manager name
                red_team = self.all_teams_df[
                    (self.all_teams_df['team_name'] == red_manager) & 
                    (self.all_teams_df['league'] == 'red')
                ]
                
                # Map the cross-league opponents correctly
                if not brown_team.empty and not red_team.empty:
                    brown_team_id = brown_team.iloc[0]['team_id']
                    red_team_id = red_team.iloc[0]['team_id']
                    
                    if league == 'brown':
                        cross_opponents[brown_team_id] = red_team_id
                    else:  # red league
                        cross_opponents[red_team_id] = brown_team_id
        
        # Process each team in this league
        for team_id, score in scores.items():
            # Find intra-league opponent
            intra_opponent = None
            intra_opponent_score = 0
            for _, matchup in week_matchups.iterrows():
                if matchup['away_team_id'] == team_id:
                    intra_opponent = matchup['home_team_id']
                    intra_opponent_score = scores.get(intra_opponent, 0)
                elif matchup['home_team_id'] == team_id:
                    intra_opponent = matchup['away_team_id'] 
                    intra_opponent_score = scores.get(intra_opponent, 0)
            
            # Get cross-league opponent
            cross_opponent = cross_opponents.get(team_id)
            cross_opponent_score = 0
            if cross_opponent:
                # Get score from the other league's scores
                other_league_scores = self.red_api.get_live_scores(week) if league == 'brown' else self.brown_api.get_live_scores(week)
                cross_opponent_score = other_league_scores.get(cross_opponent, 0)
            
            # Calculate points (only if week is complete)
            intra_points = 0
            cross_points = 0
            top6_points = 0
            
            if week_complete:
                # Intra-league points
                if intra_opponent and score > intra_opponent_score:
                    intra_points = 1
                
                # Cross-league points
                if cross_opponent and score > cross_opponent_score:
                    cross_points = 1
                
                # Top 6 points
                if team_id in top6_teams:
                    top6_points = 1
            
            # Calculate wins and losses
            wins = intra_points + cross_points + top6_points
            losses = 3 - wins if week_complete else 0
            
            league_data.append({
                'week': week,
                'team_id': team_id,
                'league': league,
                'actual_score': score,
                'intra_opponent': intra_opponent,
                'intra_opponent_score': intra_opponent_score,
                'cross_opponent': cross_opponent,
                'cross_opponent_score': cross_opponent_score,
                'intra_league_points': intra_points,
                'cross_league_points': cross_points,
                'top6_points': top6_points,
                'total_weekly_points': wins,
                'weekly_losses': losses,
                'week_complete': week_complete
            })
        
        return league_data

def main():
    st.title("🏈 Sister Leagues Dashboard")
    st.sidebar.title("Controls")
    
    # Initialize APIs for both leagues
    brown_api = ESPNFantasyAPI("brown")
    red_api = ESPNFantasyAPI("red")
    sheets_manager = GoogleSheetsManager()
    
    # Get current week
    current_week = brown_api.get_current_week()
    
    # Week selector
    selected_week = st.sidebar.selectbox(
        "Select Week",
        range(1, 15),
        index=current_week-1
    )
    
    # Manual refresh button
    if st.sidebar.button("🔄 Refresh Data", type="primary"):
        refresh_data(sheets_manager, brown_api, red_api, selected_week)
    
    # Page selector - UPDATED: Removed Live Scores and Weekly Rankings
    page = st.sidebar.selectbox(
        "Select View", 
        ["Weekly Matchups", "Season Standings", "Records"]
    )
    
    # Load teams data for both leagues - ALWAYS use Google Sheets
    all_teams = sheets_manager.get_worksheet_data("teams")
    
    if all_teams.empty:
        st.error("No team data found in Google Sheets. Please check the 'teams' tab.")
        return
    
    if all_teams.empty:
        st.error("Unable to load team data")
        return
    
    # Render selected page
    if page == "Weekly Matchups":
        show_weekly_matchups(all_teams, brown_api, red_api, sheets_manager, selected_week)
    elif page == "Season Standings":
        show_season_standings(all_teams, sheets_manager)
    elif page == "Records":
        show_records(all_teams, sheets_manager)

def refresh_data(sheets_manager, brown_api, red_api, week):
    """Refresh data from both leagues"""
    with st.spinner("Refreshing data..."):
        try:
            # DON'T refresh team data - preserve manual Google Sheets data
            all_teams = sheets_manager.get_worksheet_data("teams")
            
            if all_teams.empty:
                # Only get teams from ESPN if no manual data exists
                brown_teams = brown_api.get_teams()
                try:
                    red_teams = red_api.get_teams()
                    all_teams = pd.concat([brown_teams, red_teams], ignore_index=True)
                except:
                    all_teams = brown_teams
                    st.warning("Red Line League data not available")
                sheets_manager.update_worksheet("teams", all_teams)
                st.info("Created initial team data from ESPN")
            else:
                st.info("Using existing team data from Google Sheets")
            
            # Calculate comprehensive scores
            calculator = ScoreCalculator(all_teams, brown_api, red_api, sheets_manager)
            weekly_data = calculator.calculate_weekly_scores(week)
            
            if not weekly_data.empty:
                # Only save to sheets if week is complete
                if brown_api.is_week_complete(week):
                    sheets_manager.update_worksheet("weekly_scores", weekly_data)
                    st.success("Week complete - Data saved to Google Sheets!")
                else:
                    st.success("Live data refreshed!")
            else:
                st.warning("No data available for this week")
                
        except Exception as e:
            st.error(f"Error refreshing data: {e}")

def show_weekly_matchups(all_teams, brown_api, red_api, sheets_manager, week):
    """Show weekly matchups for all leagues - UPDATED: Stacked vertically in specified order"""
    st.header(f"Week {week} Matchups")
    
    # Get current scores for display
    brown_scores = brown_api.get_live_scores(week)
    red_scores = red_api.get_live_scores(week)
    all_scores = {**brown_scores, **red_scores}
    
    # Get matchups from APIs
    brown_matchups = brown_api.get_matchups(week)
    red_matchups = red_api.get_matchups(week)
    
    # Get cross-league matchups from sheets
    cross_matchups = sheets_manager.get_worksheet_data("matchups")
    week_cross_matchups = cross_matchups[cross_matchups['week'] == week] if not cross_matchups.empty else pd.DataFrame()
    
    # UPDATED: Stack sections vertically in specified order
    st.subheader("🔴 Red Line League Matchups")
    display_intra_league_matchups(red_matchups, all_teams, all_scores, week, 'red')
    
    st.subheader("🤎 Brown Line League Matchups")
    display_intra_league_matchups(brown_matchups, all_teams, all_scores, week, 'brown')
    
    st.subheader("⚔️ Cross-League Matchups")
    display_cross_league_matchups(week_cross_matchups, all_teams, all_scores)
    
    st.subheader("🏆 Top 6 Scoreboard")  # UPDATED: Changed title from "All Teams Leaderboard"
    display_all_teams_leaderboard(all_teams, all_scores)

def display_intra_league_matchups(matchups, all_teams, all_scores, week, league):
    """Display intra-league matchups"""
    week_matchups = matchups[matchups['week'] == week] if not matchups.empty else pd.DataFrame()
    
    if week_matchups.empty:
        st.info(f"No {league} line league matchups found for week {week}")  # UPDATED: Added "line"
        return
    
    for _, matchup in week_matchups.iterrows():
        away_id = matchup['away_team_id']
        home_id = matchup['home_team_id']
        
        # Get team names
        away_team = all_teams[all_teams['team_id'] == away_id]
        home_team = all_teams[all_teams['team_id'] == home_id]
        
        away_name = away_team.iloc[0]['team_name'] if not away_team.empty else f"Team {away_id}"
        home_name = home_team.iloc[0]['team_name'] if not home_team.empty else f"Team {home_id}"
        
        # Get scores
        away_score = all_scores.get(away_id, 0)
        home_score = all_scores.get(home_id, 0)
        
        # Display matchup
        with st.container():
            col_away, col_vs, col_home = st.columns([2, 1, 2])
            
            with col_away:
                st.write(f"**{away_name}**")
                st.metric("Score", f"{away_score:.1f}")
            
            with col_vs:
                st.write("")
                st.write("**VS**")
            
            with col_home:
                st.write(f"**{home_name}**")
                st.metric("Score", f"{home_score:.1f}")
            
            st.divider()

def display_cross_league_matchups(cross_matchups, all_teams, all_scores):
    """Display cross-league matchups"""
    if cross_matchups.empty:
        st.info("No cross-league matchups found for this week")
        return
    
    for _, matchup in cross_matchups.iterrows():
        brown_manager = matchup.get('brown_league_team', '')
        red_manager = matchup.get('red_league_team', '')
        
        # Find teams by manager names
        brown_team = all_teams[
            (all_teams['team_name'] == brown_manager) & 
            (all_teams['league'] == 'brown')
        ]
        red_team = all_teams[
            (all_teams['team_name'] == red_manager) & 
            (all_teams['league'] == 'red')
        ]
        
        if brown_team.empty or red_team.empty:
            continue
        
        brown_id = brown_team.iloc[0]['team_id']
        red_id = red_team.iloc[0]['team_id']
        
        # Get scores
        brown_score = all_scores.get(brown_id, 0)
        red_score = all_scores.get(red_id, 0)
        
        # Display matchup
        with st.container():
            col_brown, col_vs, col_red = st.columns([2, 1, 2])
            
            with col_brown:
                st.write(f"🤎 **{brown_manager}**")
                st.metric("Score", f"{brown_score:.1f}")
            
            with col_vs:
                st.write("")
                st.write("**VS**")
            
            with col_red:
                st.write(f"🔴 **{red_manager}**")
                st.metric("Score", f"{red_score:.1f}")
            
            st.divider()

def display_all_teams_leaderboard(all_teams, all_scores):
    """Display all 12 teams sorted by current week score"""
    # Create leaderboard data
    leaderboard = []
    
    for _, team in all_teams.iterrows():
        team_id = team['team_id']
        score = all_scores.get(team_id, 0)
        
        leaderboard.append({
            'rank': 0,  # Will be filled after sorting
            'team_name': team['team_name'],
            'league': team['league'],
            'score': score
        })
    
    # Sort by score and add ranks
    leaderboard.sort(key=lambda x: x['score'], reverse=True)
    for i, team in enumerate(leaderboard):
        team['rank'] = i + 1
    
    # Display leaderboard
    for team in leaderboard:
        league_emoji = "🤎" if team['league'] == 'brown' else "🔴"
        
        col1, col2, col3 = st.columns([1, 3, 2])
        
        with col1:
            rank_display = f"#{team['rank']}"
            if team['rank'] <= 6:
                rank_display += " ⭐"
            st.write(rank_display)
        
        with col2:
            st.write(f"{league_emoji} **{team['team_name']}**")
        
        with col3:
            st.metric("", f"{team['score']:.1f}")

def show_season_standings(all_teams, sheets_manager):
    """Show season standings for both leagues"""
    st.header("Season Standings")
    
    weekly_scores_df = sheets_manager.get_worksheet_data("weekly_scores")
    
    if weekly_scores_df.empty:
        st.warning("No historical data available yet")
        return
    
    # FIXED: Handle the league column issue - ensure it exists in the data
    if 'league' not in weekly_scores_df.columns:
        # If no league column exists, try to infer it from team_id patterns
        # Team IDs are formatted as: brown_1, brown_2, etc. and red_1, red_6, etc.
        def infer_league(team_id):
            try:
                team_id_str = str(team_id).lower()
                if team_id_str.startswith('brown_'):
                    return 'brown'
                elif team_id_str.startswith('red_'):
                    return 'red'
                else:
                    return 'unknown'
            except:
                return 'unknown'
        
        weekly_scores_df['league'] = weekly_scores_df['team_id'].apply(infer_league)
    
    # Clean and standardize the league column
    weekly_scores_df['league'] = weekly_scores_df['league'].astype(str).str.strip().str.lower()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🤎 Brown Line League")  # UPDATED: Added "Line"
        display_league_standings(weekly_scores_df, all_teams, 'brown')
    
    with col2:
        st.subheader("🔴 Red Line League")   # UPDATED: Added "Line"
        display_league_standings(weekly_scores_df, all_teams, 'red')

def display_league_standings(weekly_scores_df, all_teams, league):
    """Display standings for one league"""
    # Use cleaned league column and handle potential data type mismatches
    league_data = weekly_scores_df[weekly_scores_df['league'] == league]
    
    if league_data.empty:
        st.info(f"No {league} line league data available yet")  # UPDATED: Added "line"
        return
    
    # Ensure numeric columns are properly converted
    numeric_cols = ['total_weekly_points', 'weekly_losses', 'actual_score']
    for col in numeric_cols:
        if col in league_data.columns:
            league_data[col] = pd.to_numeric(league_data[col], errors='coerce').fillna(0)
    
    standings = league_data.groupby('team_id').agg({
        'total_weekly_points': 'sum',
        'weekly_losses': 'sum',
        'actual_score': 'sum'
    }).reset_index()
    
    standings.rename(columns={
        'total_weekly_points': 'wins',
        'weekly_losses': 'losses',
        'actual_score': 'total_points'
    }, inplace=True)
    
    # Handle team_id matching more robustly
    standings['team_id'] = standings['team_id'].astype(str)
    all_teams_copy = all_teams.copy()
    all_teams_copy['team_id'] = all_teams_copy['team_id'].astype(str)
    
    standings = standings.merge(
        all_teams_copy[['team_id', 'team_name']], 
        on='team_id',
        how='left'
    )
    
    # Fill missing team names
    standings['team_name'] = standings['team_name'].fillna('Unknown Team')
    
    standings = standings.sort_values('wins', ascending=False).reset_index(drop=True)
    standings['rank'] = standings.index + 1
    standings['record'] = standings['wins'].astype(str) + '-' + standings['losses'].astype(str)
    
    st.dataframe(
        standings[['rank', 'team_name', 'record', 'total_points']],
        column_config={
            "rank": "Rank",
            "team_name": "Team",
            "record": "Record (W-L)",
            "total_points": "Total Points"
        },
        use_container_width=True,
        hide_index=True
    )

def show_records(all_teams, sheets_manager):
    """Show detailed W-L records"""
    st.header("Team Records")
    
    weekly_scores_df = sheets_manager.get_worksheet_data("weekly_scores")
    
    if weekly_scores_df.empty:
        st.warning("No historical data available yet")
        return
    
    # FIXED: Handle the league column issue - ensure it exists in the data
    if 'league' not in weekly_scores_df.columns:
        # If no league column exists, try to infer it from team_id patterns
        # Brown league team IDs are typically 1-6, Red league are 101-106
        def infer_league(team_id):
            try:
                tid = int(team_id)
                return 'red' if tid > 100 else 'brown'
            except:
                return 'unknown'
        
        weekly_scores_df['league'] = weekly_scores_df['team_id'].apply(infer_league)
    
    # Clean and standardize the league column
    weekly_scores_df['league'] = weekly_scores_df['league'].astype(str).str.strip().str.lower()
    
    # Ensure numeric columns are properly converted
    numeric_cols = ['intra_league_points', 'cross_league_points', 'top6_points', 'total_weekly_points', 'weekly_losses']
    for col in numeric_cols:
        if col in weekly_scores_df.columns:
            weekly_scores_df[col] = pd.to_numeric(weekly_scores_df[col], errors='coerce').fillna(0)
    
    # Calculate detailed records
    records = weekly_scores_df.groupby(['team_id', 'league']).agg({
        'intra_league_points': 'sum',
        'cross_league_points': 'sum', 
        'top6_points': 'sum',
        'total_weekly_points': 'sum',
        'weekly_losses': 'sum'
    }).reset_index()
    
    # Handle team_id matching more robustly
    records['team_id'] = records['team_id'].astype(str)
    all_teams_copy = all_teams.copy()
    all_teams_copy['team_id'] = all_teams_copy['team_id'].astype(str)
    
    records = records.merge(
        all_teams_copy[['team_id', 'team_name']], 
        on='team_id',
        how='left'
    )
    
    # Fill missing team names
    records['team_name'] = records['team_name'].fillna('Unknown Team')
    
    # Display combined table
    records['total_record'] = records['total_weekly_points'].astype(str) + '-' + records['weekly_losses'].astype(str)
    records = records.sort_values('total_weekly_points', ascending=False)
    
    st.dataframe(
        records[['team_name', 'league', 'total_record', 'intra_league_points', 
                'cross_league_points', 'top6_points']],
        column_config={
            "team_name": "Team",
            "league": "League", 
            "total_record": "Overall Record",
            "intra_league_points": "Intra-League Wins",
            "cross_league_points": "Cross-League Wins",
            "top6_points": "Top 6 Wins"
        },
        use_container_width=True,
        hide_index=True
    )

if __name__ == "__main__":
    main()
