# debug_app.py - Debug version to isolate issues
import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Brown League Debug", layout="wide")

def test_espn_api():
    """Test ESPN API connection and data parsing"""
    st.header("ESPN API Test")
    
    try:
        # Basic API call
        url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2024/segments/0/leagues/1732780114"
        
        # Test without auth first
        params = {"view": "mTeam"}
        response = requests.get(url, params=params)
        
        st.write(f"**Status Code:** {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Show basic league info
            st.write(f"**League ID:** {data.get('id')}")
            st.write(f"**Game ID:** {data.get('gameId')}")
            
            # Parse teams
            teams = []
            for team in data.get('teams', []):
                teams.append({
                    'team_id': team['id'],
                    'location': team.get('location', 'Unknown'),
                    'nickname': team.get('nickname', 'Team'),
                    'team_name': f"{team.get('location', 'Team')} {team.get('nickname', str(team['id']))}",
                    'owner_id': team.get('primaryOwner', 'Unknown')
                })
            
            teams_df = pd.DataFrame(teams)
            st.subheader("Teams Data")
            st.dataframe(teams_df)
            
            return teams_df
        else:
            st.error(f"API Error: {response.status_code}")
            st.write(response.text[:500])
            return None
            
    except Exception as e:
        st.error(f"Exception: {str(e)}")
        return None

def test_espn_matchups():
    """Test matchups API"""
    st.header("ESPN Matchups Test")
    
    try:
        url = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2024/segments/0/leagues/1732780114"
        params = {"view": "mMatchup"}
        
        # Try with cookies if available
        cookies = {}
        if 'swid' in st.secrets and 'espn_s2' in st.secrets:
            cookies = {
                'SWID': st.secrets['swid'],
                'espn_s2': st.secrets['espn_s2']
            }
            st.write("**Using cookies for authentication**")
        else:
            st.warning("No ESPN cookies found in secrets")
        
        response = requests.get(url, params=params, cookies=cookies)
        st.write(f"**Status Code:** {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Debug: Show raw schedule data structure
            schedule = data.get('schedule', [])
            st.write(f"**Total schedule entries:** {len(schedule)}")
            
            if len(schedule) > 0:
                st.subheader("Raw Schedule Sample (First Entry)")
                first_game = schedule[0]
                st.json({
                    'matchupPeriodId': first_game.get('matchupPeriodId'),
                    'away_teamId': first_game.get('away', {}).get('teamId'),
                    'home_teamId': first_game.get('home', {}).get('teamId'),
                    'away_keys': list(first_game.get('away', {}).keys()),
                    'home_keys': list(first_game.get('home', {}).keys())
                })
            
            # Parse matchups
            matchups = []
            for game in schedule:
                if 'away' not in game or 'home' not in game:
                    continue
                    
                week_num = game.get('matchupPeriodId', 0)
                away_team = game['away'].get('teamId')
                home_team = game['home'].get('teamId')
                
                if not away_team or not home_team:
                    continue
                
                # Get scores from the correct field
                away_score = 0
                home_score = 0
                
                # Try different score fields
                if 'pointsByScoringPeriod' in game['away']:
                    away_score = game['away']['pointsByScoringPeriod'].get(str(week_num), 0)
                elif 'totalPoints' in game['away']:
                    away_score = game['away']['totalPoints']
                    
                if 'pointsByScoringPeriod' in game['home']:
                    home_score = game['home']['pointsByScoringPeriod'].get(str(week_num), 0) 
                elif 'totalPoints' in game['home']:
                    home_score = game['home']['totalPoints']
                
                matchups.append({
                    'week': week_num,
                    'away_team_id': away_team,
                    'away_score': away_score,
                    'home_team_id': home_team,
                    'home_score': home_score,
                    'winner': game.get('winner', 'TBD')
                })
            
            matchups_df = pd.DataFrame(matchups)
            st.write(f"**Total parsed matchups:** {len(matchups_df)}")
            
            if not matchups_df.empty:
                # Only show completed games
                completed_games = matchups_df[(matchups_df['away_score'] > 0) | (matchups_df['home_score'] > 0)]
                st.write(f"**Completed games:** {len(completed_games)}")
                
                st.subheader("All Matchups (Including Unplayed)")
                st.dataframe(matchups_df)
                
                if not completed_games.empty:
                    st.subheader("Completed Games Only")
                    st.dataframe(completed_games)
                    return completed_games
                else:
                    st.warning("No completed games found")
                    return matchups_df  # Return all matchups even if no scores
            else:
                st.error("No matchups parsed from API response")
                return pd.DataFrame()  # Return empty DataFrame
            
        else:
            st.error(f"Matchups API Error: {response.status_code}")
            st.write("Response content:", response.text[:500])
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Exception in matchups test: {str(e)}")
        import traceback
        st.error(traceback.format_exc())
        return pd.DataFrame()

def test_google_sheets():
    """Test Google Sheets connection"""
    st.header("Google Sheets Test")
    
    try:
        # Check if secrets exist
        required_keys = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email', 'client_id', 'auth_uri', 'token_uri', 'sheet_id']
        missing_keys = []
        
        for key in required_keys:
            if key not in st.secrets.get('google', {}):
                missing_keys.append(key)
        
        if missing_keys:
            st.error(f"Missing Google secrets: {missing_keys}")
            return None
        
        # Try to connect
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
        gc = gspread.authorize(credentials)
        
        st.success("✅ Google Sheets authentication successful!")
        
        # Try to open the sheet
        sheet_id = st.secrets["google"]["sheet_id"]
        spreadsheet = gc.open_by_key(sheet_id)
        
        st.success(f"✅ Successfully opened spreadsheet: {spreadsheet.title}")
        
        # List worksheets
        worksheets = [ws.title for ws in spreadsheet.worksheets()]
        st.write(f"**Available worksheets:** {worksheets}")
        
        # Test writing data
        test_data = pd.DataFrame({
            'test_column': ['test_value1', 'test_value2'],
            'timestamp': [datetime.now().strftime('%Y-%m-%d %H:%M:%S')] * 2
        })
        
        # Try to write to a test sheet
        try:
            test_worksheet = spreadsheet.worksheet("test_data")
        except:
            # Create test sheet if it doesn't exist
            test_worksheet = spreadsheet.add_worksheet("test_data", rows=100, cols=10)
        
        # Write test data
        test_worksheet.clear()
        test_worksheet.update([test_data.columns.values.tolist()] + test_data.values.tolist())
        
        st.success("✅ Successfully wrote test data to Google Sheets!")
        st.dataframe(test_data)
        
        return gc, spreadsheet
        
    except Exception as e:
        st.error(f"Google Sheets Error: {str(e)}")
        return None, None

def process_and_write_data(teams_df, matchups_df, spreadsheet):
    """Process the data and write to sheets"""
    st.header("Data Processing & Writing Test")
    
    if teams_df is None or matchups_df is None or spreadsheet is None:
        st.error("Missing required data - cannot process")
        return
    
    try:
        # Process weekly scoring
        weekly_scores = []
        
        for _, matchup in matchups_df.iterrows():
            week = matchup['week']
            away_team = matchup['away_team_id']
            home_team = matchup['home_team_id']
            away_score = matchup['away_score']
            home_score = matchup['home_score']
            
            # Determine winner
            if away_score > home_score:
                away_points = 1
                home_points = 0
            elif home_score > away_score:
                away_points = 0
                home_points = 1
            else:
                away_points = 0.5
                home_points = 0.5
            
            # Add away team record
            weekly_scores.append({
                'week': week,
                'team_id': away_team,
                'actual_score': away_score,
                'opponent_id': home_team,
                'opponent_score': home_score,
                'intra_league_points': away_points,
                'cross_league_points': 0,  # Not implemented yet
                'top6_points': 1,  # Everyone gets 1 since only 6 teams
                'total_weekly_points': away_points + 1
            })
            
            # Add home team record
            weekly_scores.append({
                'week': week,
                'team_id': home_team,
                'actual_score': home_score,
                'opponent_id': away_team,
                'opponent_score': away_score,
                'intra_league_points': home_points,
                'cross_league_points': 0,
                'top6_points': 1,
                'total_weekly_points': home_points + 1
            })
        
        weekly_df = pd.DataFrame(weekly_scores)
        
        st.subheader("Processed Weekly Data")
        st.dataframe(weekly_df)
        
        # Write to Google Sheets
        try:
            # Update teams sheet
            teams_worksheet = spreadsheet.worksheet("teams")
            teams_worksheet.clear()
            teams_worksheet.update([teams_df.columns.values.tolist()] + teams_df.values.tolist())
            st.success("✅ Teams data written to Google Sheets!")
            
            # Update weekly scores sheet
            weekly_worksheet = spreadsheet.worksheet("weekly_scores")
            weekly_worksheet.clear()
            weekly_worksheet.update([weekly_df.columns.values.tolist()] + weekly_df.values.tolist())
            st.success("✅ Weekly scores written to Google Sheets!")
            
        except Exception as e:
            st.error(f"Error writing to sheets: {str(e)}")
        
        return weekly_df
        
    except Exception as e:
        st.error(f"Data processing error: {str(e)}")
        return None

def main():
    st.title("🤎 Brown League Debug Dashboard")
    
    st.markdown("""
    This debug app tests each component individually to identify issues:
    1. ESPN API connection and data parsing
    2. Google Sheets authentication and write access
    3. Data processing and final write operation
    """)
    
    # Test 1: ESPN API
    teams_df = test_espn_api()
    
    st.markdown("---")
    
    # Test 2: ESPN Matchups
    matchups_df = test_espn_matchups()
    
    st.markdown("---")
    
    # Test 3: Google Sheets
    gc, spreadsheet = test_google_sheets()
    
    st.markdown("---")
    
    # Test 4: Full process
    if st.button("🚀 Run Full Data Processing Test"):
        weekly_df = process_and_write_data(teams_df, matchups_df, spreadsheet)
        
        if weekly_df is not None:
            st.success("🎉 Full process completed successfully!")
            
            # Show summary stats
            st.subheader("Summary Statistics")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Games", len(matchups_df) if matchups_df is not None else 0)
            with col2:
                st.metric("Total Teams", len(teams_df) if teams_df is not None else 0)
            with col3:
                st.metric("Weeks Processed", weekly_df['week'].nunique() if weekly_df is not None else 0)

if __name__ == "__main__":
    main()
