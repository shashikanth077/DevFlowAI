import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { api, errorMessage, tokenStorage } from '../services/api';
import type { User } from '../types';

interface AuthState {
  token: string | null;
  user: User | null;
  status: 'idle' | 'loading' | 'error';
  error: string | null;
}

const initialState: AuthState = { token: tokenStorage.get(), user: null, status: 'idle', error: null };

export const login = createAsyncThunk<{ token: string; user: User }, { email: string; password: string }, { rejectValue: string }>(
  'auth/login',
  async (credentials, { rejectWithValue }) => {
    try {
      const { access_token } = await api.login(credentials);
      tokenStorage.set(access_token);
      const user = await api.me();
      return { token: access_token, user };
    } catch (error) {
      tokenStorage.set(null);
      return rejectWithValue(errorMessage(error));
    }
  },
);

export const register = createAsyncThunk<
  { token: string; user: User },
  { email: string; password: string; full_name: string },
  { rejectValue: string }
>('auth/register', async (body, { rejectWithValue }) => {
  try {
    await api.register(body);
    const { access_token } = await api.login({ email: body.email, password: body.password });
    tokenStorage.set(access_token);
    return { token: access_token, user: await api.me() };
  } catch (error) {
    return rejectWithValue(errorMessage(error));
  }
});

export const loadUser = createAsyncThunk<User, void, { rejectValue: string }>('auth/me', async (_, { rejectWithValue }) => {
  try {
    return await api.me();
  } catch (error) {
    return rejectWithValue(errorMessage(error));
  }
});

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    logout(state) {
      tokenStorage.set(null);
      state.token = null;
      state.user = null;
      state.status = 'idle';
    },
  },
  extraReducers: (builder) => {
    for (const thunk of [login, register]) {
      builder
        .addCase(thunk.pending, (state) => {
          state.status = 'loading';
          state.error = null;
        })
        .addCase(thunk.fulfilled, (state, action) => {
          state.status = 'idle';
          state.token = action.payload.token;
          state.user = action.payload.user;
        })
        .addCase(thunk.rejected, (state, action) => {
          state.status = 'error';
          state.error = action.payload ?? 'Authentication failed';
        });
    }
    builder
      .addCase(loadUser.fulfilled, (state, action) => {
        state.user = action.payload;
      })
      .addCase(loadUser.rejected, (state) => {
        tokenStorage.set(null);
        state.token = null;
        state.user = null;
      });
  },
});

export const { logout } = authSlice.actions;
export default authSlice.reducer;
