import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Player } from './Player';
import type { Job } from './types';

afterEach(cleanup);

it('lets the skip buttons supersede an unfinished timeline seek', () => {
  const job = { id: 'review89', source_url_path: '/api/jobs/review89/source',
    width: 1280, height: 720, duration: 60 } as Job;
  const onTime = vi.fn();
  render(<Player job={job} cues={[]} onTime={onTime} seek={{time: 30, token: 1}} />);
  const video = screen.getByLabelText('Video gốc') as HTMLVideoElement;
  fireEvent.click(screen.getByRole('button', {name: 'Tiến 5 giây'}));
  fireEvent.seeked(video);
  expect(video.currentTime).toBe(35);
  expect(onTime).toHaveBeenLastCalledWith(35);
  fireEvent.click(screen.getByRole('button', {name: 'Lùi 5 giây'}));
  fireEvent.seeked(video);
  expect(video.currentTime).toBe(30);
  expect(onTime).toHaveBeenLastCalledWith(30);
});

it('keeps the newest shared seek when an older video seek reports timeupdate', () => {
  const job = { id: 'review89', source_url_path: '/api/jobs/review89/source',
    width: 1280, height: 720, duration: 60 } as Job;
  const onTime = vi.fn();
  const { rerender } = render(<Player job={job} cues={[]} onTime={onTime} seek={{time: 10, token: 1}} />);
  const video = screen.getByLabelText('Video gốc') as HTMLVideoElement;
  rerender(<Player job={job} cues={[]} onTime={onTime} seek={{time: 30, token: 2}} />);
  // An asynchronous completion of the earlier native seek arrives late.
  video.currentTime = 10;
  fireEvent.timeUpdate(video);
  fireEvent.seeked(video);
  expect(onTime).not.toHaveBeenCalledWith(10);
  expect(video.currentTime).toBe(30);
  video.currentTime = 30;
  fireEvent.seeked(video);
  fireEvent.timeUpdate(video);
  expect(onTime).toHaveBeenLastCalledWith(30);
  // Normal playback must still advance the common playhead.
  video.currentTime = 31;
  fireEvent.timeUpdate(video);
  expect(onTime).toHaveBeenLastCalledWith(31);
});
