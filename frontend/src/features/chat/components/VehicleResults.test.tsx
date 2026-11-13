import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VehicleResults } from "./VehicleResults";

describe("VehicleResults", () => {
  it("renders images and exposes conversational result actions", () => {
    const showMore = vi.fn();
    const getDetails = vi.fn();

    render(
      <VehicleResults
        result={{
          has_more: true,
          filter_warnings: ["No available Fuel type option matched: Hybrid"],
          vehicles: [
            {
              title: "2024 Toyota Camry SE",
              lot_number: "12345678",
              image_url: "https://example.test/camry.jpg",
              yard_location: "TX - Dallas",
              current_bid: "$750.00",
            },
          ],
        }}
        onShowMore={showMore}
        onGetDetails={getDetails}
      />,
    );

    expect(screen.getByAltText("2024 Toyota Camry SE")).toHaveAttribute(
      "src",
      "https://example.test/camry.jpg",
    );
    expect(screen.queryByText("Some criteria were unavailable")).not.toBeInTheDocument();
    expect(screen.queryByText(/No available Fuel type/)).not.toBeInTheDocument();
    expect(screen.getByText("Current bid")).toBeInTheDocument();
    expect(screen.getByText("$750.00")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    fireEvent.click(screen.getByRole("button", { name: "Show me more vehicles" }));
    expect(getDetails).toHaveBeenCalledWith("12345678");
    expect(showMore).toHaveBeenCalledOnce();
  });

  it("renders no more than four listing cards", () => {
    render(
      <VehicleResults
        result={{
          vehicles: Array.from({ length: 5 }, (_, index) => ({
            title: `Vehicle ${index + 1}`,
            lot_number: `1234567${index}`,
            current_bid: "$100.00",
          })),
        }}
        onShowMore={() => undefined}
        onGetDetails={() => undefined}
      />,
    );

    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.queryByText("Vehicle 5")).not.toBeInTheDocument();
  });
});
