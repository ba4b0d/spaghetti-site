import { describe, it, expect } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { PageLoader } from '../App';

describe('PageLoader', () => {
  it('shows the Spaghetti Prints branded loading experience', () => {
    const { container } = render(<PageLoader />);

    expect(screen.getByText('اسپاگتی پرینت')).toBeTruthy();
    expect(screen.getByText('در حال آمادهسازی چاپ سه بعدی شما')).toBeTruthy();
    expect(container.querySelector('.spaghetti-loader__printer')).toBeTruthy();
  });
});
