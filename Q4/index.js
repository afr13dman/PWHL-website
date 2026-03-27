// define the dimensions and margins for the line chart
    // Use the Margin Convention referenced in the HW document to layout your graph
    const margin = {top: 60, right: 10, bottom: 50, left: 50},
          width = 1000,
          height = 500

    // define the dimensions and margins for the bar chart


    // append svg element to the body of the page
    // set dimensions and position of the svg element
    let svg = d3
      .select("body")
      .append("svg")
      .attr("id", "line_chart")
      .attr("width", width + margin.right + margin.left)
      .attr("height", height + margin.top + margin.bottom)
      .append("g")
      .attr("id", "container")
      .attr("transform",
        "translate(" + margin.left + "," + margin.top + ")");

    // Fetch the data
	var pathToCsv = "average-rating.csv";


    d3.dsv(",", pathToCsv, function (d) {
      return {
        // format data attributes if required
        average_rating: Math.floor(+d.average_rating),
        name: d.name,
        users_rated: +d.users_rated,
        year: +d.year
      }
    }).then(function (data) {
        console.log(data); // you should see the data in your browser's developer tools console

        /* Create bar plot using data from csv */
        // create nested object of counts by year
        const uniqueRatings = new Set([0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        const counts = {}
        var maxCount = 0
        for(let year = 2015; year <= 2019; year++) {
            counts[year] = []
            for (const rating of uniqueRatings){
                const count = {rating: rating, count: d3.sum(Array.from(data), d => d.average_rating == rating & d.year == year)}
                counts[year].push(count)
                if (count.count > maxCount) { maxCount = count.count }
            }
        }
        
        container = d3.select("#container")
        
        // axis scales
        x = d3.scaleLinear()
            .domain([0, d3.max(Array.from(data), d => d.average_rating)])
            .range([0, width])
        
        y = d3.scaleLinear()
            .domain([0, maxCount])
            .range([height, 0])

        colors = d3.scaleOrdinal(["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"])

        
        // assemble axes and axis labels
        container.append("g")
            .attr("id", "x-axis-lines")
            .call(d3.axisBottom(x))
            .attr("transform", `translate(0, ${height})`)
            .append("text")
                .text("Rating")
                .attr('fill', 'black')
                .attr("x", width / 2 + margin.left)
                .attr("y", margin.bottom / 1.5)
                .style('font-family', 'Arial')
                .style('font-size', '17px')
                .style('text-anchor', 'middle')
        container.append("g")
            .attr("id", "y-axis-lines")
            .call(d3.axisLeft(y))
            .append("text")
                .text("Count")
                .attr('fill', 'black')
                .style('font-family', 'Arial')
                .style('font-size', '17px')
                .attr("transform", `translate(${-margin.left/1.5}, ${height/2}), rotate(-90)`)
                .style('text-anchor', 'middle')

        // assemble lines
        lines = container.append("g")
            .attr("id", "lines")
        linesFunc = d3.line()
            .x(d => x(d.rating))
            .y(d => y(d.count))
        for(const i of Object.entries(counts)) {
            const year = i[0]
            const values = Object.values(i[1])
            values.sort((a,b) => a.rating - b.rating)
            lines.append("path")
                .attr("d", linesFunc(values))
                .attr('fill', 'none')
                .attr('stroke', colors(year))
                .style('stroke-width', 2)
        }

        // assemble circles + event handling
        circles = container.append("g")
            .attr("id", "circles")
        circles.selectAll('circle')
            .data(Object.entries(counts))
            .enter()
            .each(function(d) {
                const year = d[0]
                const values = d[1]
                for(i=0; i<values.length; i++){
                    const smallCircle = 3
                    const rating = values[i].rating
                    const count = values[i].count
                    circles.append('circle')
                        .attr("r", smallCircle)
                        .attr('fill', colors(year))
                        .attr('cx', x(rating))
                        .attr('cy', y(count))
                        .on('mouseover', function(){
                            d3.select(this)
                                .attr("r", 15)
                            d3.select('#bar_chart_title')
                                .text(`Top 5 Most Rated Games of ${year} with Rating ${rating}`)
                            generateBars(data, year, rating)
                        }).on('mouseout', function(){
                            d3.select(this)
                                .attr("r", smallCircle)
                            hideChart()
                        })
                }
            })

        // assemble title and credit
        container.append("text")
            .attr("id", "line_chart_title")
            .text("Board games by Rating 2015-2019")
            .attr("x", width/2 + margin.left)
            .attr("y", -margin.top/2)
            .style('text-anchor', 'middle')
            .style('dominant-baseline', 'middle')
            .style('font-size', '25px')

        container.append("text")
            .attr("id", "credit")
            .text("jsonnabend3")
            .attr("x", width/2 + margin.left)
            .attr("y", 0)
            .attr('fill', 'MidnightBlue')
        
        // assemble legend
        legend = container.append("g")
            .attr("id", "legend")
        const legSpacing = 20
        legend.selectAll('circle')
            .data(Object.entries(counts))
            .enter()
            .append('circle')
            .attr('fill', d => colors(d[0]))
            .attr('r', 5)
            .attr('cx', width - margin.right - 35)
            .attr('cy', (d, i) => legSpacing * i + margin.top)
        legend.selectAll('text')
            .data(Object.entries(counts))
            .enter()
            .append('text')
            .text(d => d[0])
            .attr('x', width - margin.right + 10)
            .attr('y', (d, i) => legSpacing * i + margin.top)
            .style('dominant-baseline', 'middle')
            .style('text-anchor', 'end')



        // bar parameters
        const barChartHeight = 300
        const barChartLength = 500
        
        // bar chart title
        barTitle = d3.select("body")
            .append("div")
                .attr("id", "bar_chart_title")
                .attr('text-fill', 'black')
                .attr('x', margin.left + width/2)

        // bar chart containers
        svg2 = d3.select("body")
            .append("svg")
                .attr("id", "bar_chart")
                .attr("width", width + margin.right + margin.left)
                .attr("height", height + margin.top + margin.bottom)
                .style("display", "none")
        container2 = svg2.append("g")
                .attr("id", "container_2")
                .attr("transform",
                    `translate(${margin.left + width/2 - barChartLength/2}, ${margin.top})`);


        

        // set up bar chart
        container2.append("g")
            .attr("id", "bars")
        
        container2.append("g")
            .attr("id", "x-axis-bars")
            .attr("transform", `translate(0, ${barChartHeight})`)
        container2.append("g")
            .attr("id", "y-axis-bars")
        container2.append("text")
            .attr("id", "bar_x_axis_label")
            .text("Number of users")
            .attr("x", barChartLength/2)
            .attr("y", barChartHeight + margin.bottom)
            .attr("text-anchor", "middle")
            .style('font-family', 'Arial')
            .style('font-size', '17px')
        container2.append("text")
            .attr("id", "bar_y_axis_label")
            .text("Games")
            .style('font-family', 'Arial')
            .style('font-size', '17px')
            .attr("transform", `translate(${-margin.left*1.25}, ${barChartHeight/2}), rotate(-90)`)
            .style('text-anchor', 'middle')

        
        // update bar chart
        function generateBars(data, year, rating) {
            svg2.style('display', 'unset')
            barTitle.style('display', 'block')

            const filteredData = data.filter(i => i.year == year & i.average_rating == rating)
            filteredData.sort((a,b) => b.users_rated - a.users_rated)
            const top5 = filteredData.slice(0,5)

            var x2 = d3.scaleLinear()
                .domain([0, d3.max(top5, d => d.users_rated)])
                .range([0, barChartLength])
            var y2 = d3.scaleBand()
                .domain(top5.map(d => d.name.slice(0, 10)))
                .range([0, barChartHeight])
                .padding(0.25)

            var bars = d3.select("#bars").selectAll("rect")
                .data(top5, d => d.name)
            bars.exit()
                .remove()
            bars.enter()
                .append("rect")
                .attr("y", d => y2(d.name.slice(0,10)))
                .attr("height", y2.bandwidth())
                .attr("width", d => x2(d.users_rated))
                .attr("fill", "steelblue")
                .style("opacity", 0.75)

            d3.select("#x-axis-bars")
                .call(d3.axisBottom(x2)
                        .tickSizeInner(-barChartHeight))
            d3.select("#y-axis-bars")
                .call(d3.axisLeft(y2))
            
            if(top5.length == 0) { hideChart() }
        }

        function hideChart() {
            svg2.style('display', 'none')
            barTitle.style('display', 'none')
        }

    }).catch(function (error) {
      console.log(error);
    });

