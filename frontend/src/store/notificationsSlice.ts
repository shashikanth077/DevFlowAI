import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface Notification {
  id: number;
  message: string;
  severity: 'success' | 'info' | 'warning' | 'error';
}

let nextId = 1;

const notificationsSlice = createSlice({
  name: 'notifications',
  initialState: [] as Notification[],
  reducers: {
    notify: {
      reducer(state, action: PayloadAction<Notification>) {
        state.push(action.payload);
      },
      prepare(message: string, severity: Notification['severity'] = 'info') {
        return { payload: { id: nextId++, message, severity } };
      },
    },
    dismiss(state, action: PayloadAction<number>) {
      return state.filter((n) => n.id !== action.payload);
    },
  },
});

export const { notify, dismiss } = notificationsSlice.actions;
export default notificationsSlice.reducer;
