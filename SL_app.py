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
        else:  # red league - PLACEHOLDER - update these once you have the correct names
            manager_mapping = {
                1: 'Red Team 1 Manager',  # Replace with actual manager name
                2: 'Red Team 2 Manager',  # Replace with actual manager name
                3: 'Red Team 3 Manager',  # Replace with actual manager name
                4: 'Red Team 4 Manager',  # Replace with actual manager name
                5: 'Red Team 5 Manager',  # Replace with actual manager name
                6: 'Red Team 6 Manager'   # Replace with actual manager name
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
                team_id = team['id']
                total_score = 0
                
                roster = team.get('roster', {}).get('entries', [])
                for player_entry in roster:
                    lineup_slot = player_entry.get('lineupSlotId', -1)
                    
                    if lineup_slot in starting_positions:
                        player_pool_entry = player_entry.get('playerPoolEntry', {})
                        applied_total = player_pool_entry.get('appliedStatTotal', 0)
                        total_score += applied_total
                
                team_scores[team_id] = total_score
            
            return team_scores
            
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
        # Get scores from both leagues
        brown_scores = self.brown_api.get_live_scores(week)
        red_scores = self.red_api.get_live_scores(week)
        
        # Get intra-league matchups
        brown_matchups = self.brown_api.get_matchups(week)
        red_matchups = self.red_api.get_matchups(week)
        
        # Get cross-league matchups from Google Sheets
        cross_matchups = self.sheets_manager.get_worksheet_data("matchups")
        week_cross_matchups = cross_matchups[cross_matchups['week'] == week] if not cross_matchups.empty else pd.DataFrame()
        
        # Check if week is complete
        week_complete = self.brown_api.is_week_complete(week)
        
        # Combine all scores
        all_scores = {**brown_scores, **red_scores}
        
        # Calculate top 6 teams across both leagues
        top6_teams = []
        if week_complete:
            sorted_scores = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)
            top6_teams = [team_id for team_id, score in sorted_scores[:6]]
        
        # Process each league
        weekly_data = []
        
        # Process Brown League
        weekly_data.extend(self._process_league_scores(
            brown_scores, brown_matchups, week_cross_matchups, 
            'brown', week, week_complete, top6_teams
        ))
        
        # Process Red League  
        weekly_data.extend(self._process_league_scores(
            red_scores, red_matchups, week_cross_matchups, 
            'red', week, week_complete, top6_teams
        ))
        
        return pd.DataFrame(weekly_data)
    
    def _process_league_scores(self, scores, matchups, cross_matchups, league, week, week_complete, top6_teams):
        """Process scores for a single league"""
        league_data = []
        week_matchups = matchups[matchups['week'] == week] if not matchups.empty else pd.DataFrame()
        
        # Get cross-league opponent mapping
        cross_opponents = {}
        if not cross_matchups.empty:
            for _, match in cross_matchups.iterrows():
                brown_manager = match.get('brown_league_manager', '')
                red_manager = match.get('red_league_manager', '')
                
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
    
    # Page selector
    page = st.sidebar.selectbox(
        "Select View", 
        ["Live Scores", "Weekly Rankings", "Season Standings", "Records"]
    )
    
    # Load teams data for both leagues - ALWAYS use Google Sheets
    all_teams = sheets_manager.get_worksheet_data("teams")
    
    if all_teams.empty:
        st.error("No team data found in Google Sheets. Please check the 'teams' tab.")
        return
    
    # Debug: Force refresh teams button
    if st.sidebar.button("🔄 Force Reload Teams from Sheets", key="force_reload_teams"):
        st.cache_data.clear()
        all_teams = sheets_manager.get_worksheet_data("teams")
        st.success("Teams reloaded from Google Sheets!")
    
    if all_teams.empty:
        st.error("Unable to load team data")
        return
    
    # Render selected page
    if page == "Live Scores":
        show_live_scores(all_teams, brown_api, red_api, sheets_manager, selected_week, debug_mode)
    elif page == "Weekly Rankings":
        show_weekly_rankings(all_teams, brown_api, red_api, selected_week)
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
                    st.warning("Red League data not available")
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

def force_refresh_teams(sheets_manager, brown_api, red_api):
    """Force refresh team data from ESPN (will overwrite manual changes)"""
    with st.spinner("Force refreshing team data..."):
        try:
            brown_teams = brown_api.get_teams()
            try:
                red_teams = red_api.get_teams()
                all_teams = pd.concat([brown_teams, red_teams], ignore_index=True)
            except:
                all_teams = brown_teams
                st.warning("Red League data not available")
            
            sheets_manager.update_worksheet("teams", all_teams)
            st.success("Team data forcefully refreshed from ESPN!")
            st.warning("Your manual team changes have been overwritten")
        except Exception as e:
            st.error(f"Error force refreshing teams: {e}")

def show_live_scores(all_teams, brown_api, red_api, sheets_manager, week):
    """Show live scores for both leagues"""
    st.header(f"Week {week} Live Scores")
    
    # Debug: Show what team IDs we're working with
    if st.sidebar.checkbox("Show Debug Info"):
        st.subheader("Debug Information")
        
        brown_scores = brown_api.get_live_scores(week)
        red_scores = red_api.get_live_scores(week)
        
        col1, col2 = st.columns(2)
        with col1:
            st.write("**Brown League Team IDs & Scores:**")
            for team_id, score in brown_scores.items():
                st.write(f"ID: {team_id}, Score: {score}")
        
        with col2:
            st.write("**Red League Team IDs & Scores:**")
            for team_id, score in red_scores.items():
                st.write(f"ID: {team_id}, Score: {score}")
        
        st.write("**Teams in Google Sheets:**")
        st.dataframe(all_teams[['team_id', 'team_name', 'league']])
        
        st.write("---")
    
    calculator = ScoreCalculator(all_teams, brown_api, red_api, sheets_manager)
    weekly_data = calculator.calculate_weekly_scores(week)
    
    if weekly_data.empty:
        st.warning(f"No data available for Week {week}")
        return
    
    week_complete = weekly_data.iloc[0]['week_complete'] if not weekly_data.empty else False
    
    if week_complete:
        st.success("✅ Week Complete - Points Awarded")
    else:
        st.info("🔄 Live Scoring - Points will be awarded Tuesday morning")
    
    # Show league sections
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🤎 Brown League")
        brown_data = weekly_data[weekly_data['league'] == 'brown']
        display_league_scores(brown_data, all_teams, week_complete)
    
    with col2:
        st.subheader("🔴 Red League")
        red_data = weekly_data[weekly_data['league'] == 'red']
        if not red_data.empty:
            display_league_scores(red_data, all_teams, week_complete)
        else:
            st.info("Red League data not available yet")

def display_league_scores(league_data, all_teams, week_complete):
    """Display scores for one league"""
    for _, row in league_data.iterrows():
        team_id = row['team_id']
        
        # Debug: Show what we're trying to match
        if st.sidebar.checkbox("Show Team Lookup Debug"):
            st.write(f"Looking for team_id: {team_id} (type: {type(team_id)})")
            st.write(f"Available team_ids in sheets: {list(all_teams['team_id'].values)} (types: {[type(x) for x in all_teams['team_id'].values[:3]]})")
        
        # Find team name with error handling - try both exact match and string conversion
        team_matches = all_teams[all_teams['team_id'] == team_id]['team_name']
        
        if team_matches.empty:
            # Try converting team_id to string and match
            team_matches = all_teams[all_teams['team_id'].astype(str) == str(team_id)]['team_name']
        
        if team_matches.empty:
            # Try converting both to int and match
            try:
                team_matches = all_teams[all_teams['team_id'].astype(int) == int(team_id)]['team_name']
            except:
                pass
        
        if team_matches.empty:
            team_name = f"Team {team_id} (Not Found)"
        else:
            team_name = team_matches.iloc[0]
        
        st.write(f"**{team_name}**")
        st.write(f"Score: {row['actual_score']:.1f}")
        
        if week_complete:
            record = f"{int(row['total_weekly_points'])}-{int(row['weekly_losses'])}"
            st.write(f"Week Record: {record}")
        
        st.write("---")

def show_weekly_rankings(all_teams, brown_api, red_api, week):
    """Show combined weekly rankings"""
    st.header(f"Week {week} Combined Rankings")
    
    brown_scores = brown_api.get_live_scores(week)
    red_scores = red_api.get_live_scores(week) if red_api else {}
    
    # Combine and rank all scores
    all_scores = []
    for team_id, score in {**brown_scores, **red_scores}.items():
        team_info = all_teams[all_teams['team_id'] == team_id]
        if not team_info.empty:
            all_scores.append({
                'team_id': team_id,
                'team_name': team_info.iloc[0]['team_name'],
                'league': team_info.iloc[0]['league'],
                'score': score
            })
        else:
            # Handle missing team info
            league = 'red' if team_id > 100 else 'brown'
            all_scores.append({
                'team_id': team_id,
                'team_name': f'Team {team_id} (Not Found)',
                'league': league,
                'score': score
            })
    
    if not all_scores:
        st.warning("No scores available for this week")
        return
    
    rankings_df = pd.DataFrame(all_scores)
    rankings_df = rankings_df.sort_values('score', ascending=False).reset_index(drop=True)
    rankings_df['rank'] = rankings_df.index + 1
    
    # Display rankings with top 6 indicator
    for _, row in rankings_df.iterrows():
        col1, col2, col3, col4 = st.columns([1, 1, 3, 2])
        
        with col1:
            st.write(f"**#{row['rank']}**")
        with col2:
            if row['rank'] <= 6:
                st.write("⭐")
            else:
                st.write("")
        with col3:
            league_emoji = "🤎" if row['league'] == 'brown' else "🔴"
            st.write(f"{league_emoji} **{row['team_name']}**")
        with col4:
            st.metric("Score", f"{row['score']:.1f}")

def show_season_standings(all_teams, sheets_manager):
    """Show season standings for both leagues"""
    st.header("Season Standings")
    
    weekly_scores_df = sheets_manager.get_worksheet_data("weekly_scores")
    
    if weekly_scores_df.empty:
        st.warning("No historical data available yet")
        return
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🤎 Brown League")
        display_league_standings(weekly_scores_df, all_teams, 'brown')
    
    with col2:
        st.subheader("🔴 Red League") 
        display_league_standings(weekly_scores_df, all_teams, 'red')

def display_league_standings(weekly_scores_df, all_teams, league):
    """Display standings for one league"""
    league_data = weekly_scores_df[weekly_scores_df['league'] == league]
    
    if league_data.empty:
        st.info(f"No {league} league data available yet")
        return
    
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
    
    standings = standings.merge(
        all_teams[['team_id', 'team_name']], 
        on='team_id'
    )
    
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
    
    # Calculate detailed records
    records = weekly_scores_df.groupby(['team_id', 'league']).agg({
        'intra_league_points': 'sum',
        'cross_league_points': 'sum', 
        'top6_points': 'sum',
        'total_weekly_points': 'sum',
        'weekly_losses': 'sum'
    }).reset_index()
    
    records = records.merge(all_teams[['team_id', 'team_name']], on='team_id')
    
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
